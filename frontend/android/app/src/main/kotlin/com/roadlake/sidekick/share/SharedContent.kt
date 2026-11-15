package com.roadlake.sidekick.share

/**
 * What another app shared to Sidekick, read from an `ACTION_SEND` intent (see [SharedContent.parse]). The page turns it
 * into a task or a journal entry only after the owner has seen it and pressed Save.
 *
 * [title] is the suggestion for the task title or the entry title: the sender's subject when it gave one, else the first
 * line of the text without its link, else the host of the link. It may be empty. [text] is the shared text as it came
 * (trimmed, shortened to [MAX_TEXT]). [link] is the first web address in [text].
 */
data class SharedContent(val title: String, val text: String, val link: String?) {
    companion object {
        const val ACTION_SEND = "android.intent.action.SEND"

        /** A task's description takes 10 000 characters (`Description` in companion_work_writes.py); the text is cut there. */
        const val MAX_TEXT = 10_000

        /** A task or entry title takes 200 characters. */
        const val MAX_SUBJECT = 200

        /** A title taken from the body of the text stays short: it is a suggestion the owner edits. */
        private const val MAX_TITLE_FROM_TEXT = 100

        /** Web addresses only: another scheme is never offered as a link. */
        private val LINK = Regex("""https?://[^\s<>"]+""", RegexOption.IGNORE_CASE)
        private val HOST = Regex("""^https?://(?:[^/?#@]*@)?([^/?#:]+)""", RegexOption.IGNORE_CASE)
        private const val TRAILING_PUNCTUATION = ".,;:!?)]}'\""
        private val WHITESPACE = Regex("""\s+""")

        /**
         * The shared content of an intent's parts, or null when it is not a text share or has nothing to keep. A share
         * with other data (a picture, a file) is not ours: only `text/plain` is accepted. Nothing here fails; odd input
         * only makes a plainer suggestion.
         */
        fun parse(action: String?, mimeType: String?, subject: String?, text: String?): SharedContent? {
            if (action != ACTION_SEND || !isPlainText(mimeType)) return null
            val body = clip(text.orEmpty().trim(), MAX_TEXT)
            val sentTitle = oneLine(subject.orEmpty())
            if (body.isEmpty() && sentTitle.isEmpty()) return null
            val link = LINK.find(body)?.value?.trimEnd { it in TRAILING_PUNCTUATION }?.takeIf { it.length > "https://".length }
            val title = if (sentTitle.isNotEmpty()) clip(sentTitle, MAX_SUBJECT) else titleFrom(body, link)
            return SharedContent(title = title, text = body, link = link)
        }

        private fun isPlainText(mimeType: String?): Boolean = mimeType?.substringBefore(';')?.trim().equals("text/plain", ignoreCase = true)

        private fun titleFrom(body: String, link: String?): String {
            val withoutLink = if (link == null) body else body.replace(link, " ")
            val firstLine = withoutLink.lineSequence().map { oneLine(it) }.firstOrNull { it.isNotEmpty() }
            if (firstLine != null) return clipAtWord(firstLine, MAX_TITLE_FROM_TEXT)
            val host = link?.let { HOST.find(it)?.groupValues?.get(1) }
            return host?.removePrefix("www.").orEmpty()
        }

        private fun oneLine(value: String): String = value.replace(WHITESPACE, " ").trim()

        /** At most [limit] characters, never splitting a surrogate pair. */
        private fun clip(value: String, limit: Int): String {
            if (value.length <= limit) return value
            val end = if (Character.isHighSurrogate(value[limit - 1])) limit - 1 else limit
            return value.substring(0, end)
        }

        /** At most [limit] characters, cut at a word and marked with an ellipsis. */
        private fun clipAtWord(value: String, limit: Int): String {
            if (value.length <= limit) return value
            val cut = clip(value, limit - 1)
            val atWord = cut.lastIndexOf(' ')
            return (if (atWord > limit / 2) cut.substring(0, atWord) else cut).trimEnd() + "…"
        }
    }
}
