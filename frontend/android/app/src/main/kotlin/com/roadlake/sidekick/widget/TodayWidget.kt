package com.roadlake.sidekick.widget

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.text.format.DateUtils
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.Button
import androidx.glance.ButtonDefaults
import androidx.glance.ColorFilter
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.Image
import androidx.glance.ImageProvider
import androidx.glance.LocalContext
import androidx.glance.LocalSize
import androidx.glance.action.ActionParameters
import androidx.glance.action.actionParametersOf
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.action.actionStartActivity
import androidx.glance.appwidget.appWidgetBackground
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.color.ColorProvider
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
import androidx.glance.layout.Column
import androidx.glance.layout.ColumnScope
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxHeight
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.size
import androidx.glance.layout.width
import androidx.glance.semantics.contentDescription
import androidx.glance.semantics.semantics
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextAlign
import androidx.glance.text.TextDecoration
import androidx.glance.text.TextStyle
import com.roadlake.sidekick.MainActivity
import com.roadlake.sidekick.R
import com.roadlake.sidekick.SidekickRuntime
import com.roadlake.sidekick.today.TodayNotice
import com.roadlake.sidekick.today.TodaySnapshot
import com.roadlake.sidekick.today.TodayState
import com.roadlake.sidekick.today.TodayTask
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.withContext

internal val TASK_ID = ActionParameters.Key<String>("task_id")

/** The deep links of the app (`launch-hint.ts`): they open the app on Today or on one Task. */
internal object DeepLinks {
    const val TODAY_URI = "sidekick://open?view=today"

    /** The settings, where the license row is (`launch-hint.ts`). */
    const val SETTINGS_URI = "sidekick://open?view=settings"

    fun taskUri(taskId: String): String = "sidekick://open?view=task&id=$taskId"

    fun today(context: Context): Intent = view(context, TODAY_URI)

    fun task(context: Context, taskId: String): Intent = view(context, taskUri(taskId))

    fun settings(context: Context): Intent = view(context, SETTINGS_URI)

    // Explicit (a component), so no other app can answer it and the activity needs no exported VIEW filter.
    fun view(context: Context, uri: String): Intent = Intent(context, MainActivity::class.java)
        .setAction(Intent.ACTION_VIEW)
        .setData(Uri.parse(uri))
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
}

/** The ARGB of the app's primary pair, light and dark; separate so a test can compare them with `ui/tokens.css`. */
internal object PrimaryPair {
    const val LIGHT_BG = 0xFF1F1F1FL
    const val LIGHT_FG = 0xFFFFFFFFL
    const val DARK_BG = 0xFFEDEDEDL
    const val DARK_FG = 0xFF1C1C1EL
}

/** The colours of the app's design tokens (`ui/tokens.css`), light and dark; the widget follows the system theme. */
private object Palette {
    val background = ColorProvider(day = Color(0xFFFFFFFF), night = Color(0xFF1C1C1E))
    val text = ColorProvider(day = Color(0xFF1F1F1F), night = Color(0xFFEDEDED))
    val muted = ColorProvider(day = Color(0xFF5F6368), night = Color(0xFFA1A1AA))
    val line = ColorProvider(day = Color(0xFF8A8A90), night = Color(0xFF75757D))
    val overdue = ColorProvider(day = Color(0xFFB42318), night = Color(0xFFFF8A80))

    // The app's primary pair (--sk-inverse-bg / --sk-inverse-fg in ui/tokens.css): an ink button in the light theme, a
    // light one in the dark (WidgetResourcesTest keeps the values in step with the tokens).
    val primary = ColorProvider(day = Color(PrimaryPair.LIGHT_BG), night = Color(PrimaryPair.DARK_BG))
    val onPrimary = ColorProvider(day = Color(PrimaryPair.LIGHT_FG), night = Color(PrimaryPair.DARK_FG))
}

// What the layout really draws, in dp. Measured on the emulator (4x2 and 4x4, 420 dpi): the rows, the header and the footer
// come out at exactly these heights, so the row count below is plain arithmetic on them. widget_preview.xml repeats them
// (WidgetPreviewTest keeps the two in step). The header and the rows are the touch targets (refresh, the circle, the
// task, Undo), so they are at least [MIN_TOUCH_TARGET] tall and the targets are as wide. The footer is a plain line of
// [FOOTER_HEIGHT] until it holds "+N till", a target too: then it is [MORE_FOOTER_HEIGHT] tall.
internal val MIN_TOUCH_TARGET = 48.dp
internal val HEADER_HEIGHT = MIN_TOUCH_TARGET
internal val ROW_HEIGHT = MIN_TOUCH_TARGET
internal val FOOTER_HEIGHT = 20.dp
internal val MORE_FOOTER_HEIGHT = MIN_TOUCH_TARGET
internal val PADDING = 8.dp
private const val MIN_ROWS = 1

// The system picks a declared layout once the real height is at least the declared one (it rounds to whole dp), so rows
// never overflow by more than a rounding error; this margin keeps the last row clear of the footer all the same.
internal val SAFETY_MARGIN = 2.dp

/** Padding, header and footer plus the safety margin: what a height holds besides rows. */
internal val CHROME_HEIGHT = PADDING * 2 + HEADER_HEIGHT + FOOTER_HEIGHT + SAFETY_MARGIN

// The narrowest the launcher lets the widget be (`minResizeWidth` in today_widget_info.xml); the rows do not depend on width.
private val SIZED_WIDTH = 150.dp

// Room for this many rows is declared as a size; a taller widget draws this many and says "+N till" for the rest.
// (RemoteViews takes at most 16 sized layouts; more makes the whole widget fail to draw.)
private const val MAX_SIZED_ROWS = 12

/**
 * The heights a layout is made for: exactly room for 1, 2, ... [MAX_SIZED_ROWS] rows. The smallest, the widget's
 * `minHeight`, holds one row and a footer that is a target ("+N till"), so that one is never clipped.
 */
internal fun sizedHeights(): List<Float> = (1..MAX_SIZED_ROWS).map {
    CHROME_HEIGHT.value + it * ROW_HEIGHT.value + if (it ==
        1
    ) {
        (MORE_FOOTER_HEIGHT - FOOTER_HEIGHT).value
    } else {
        0f
    }
}

/**
 * The home-screen widget "Idag". It draws from the stored Today ([TodayState]) only; reading the server is [TodaySync]'s
 * job. The number of rows follows the height the launcher gives it (at least one); what does not fit is "+N till".
 * Its texts are in the language the app has set ([WidgetLocale]), not the system's.
 *
 * The sizes are declared ([SizeMode.Responsive], one layout per row count) rather than read from the launcher
 * ([SizeMode.Exact]): Exact composes once for every size the launcher reports and the system then shows the one that
 * fits its own measure, so a launcher whose list is shorter or smaller than the real widget left a tall widget drawn with
 * two rows. With declared sizes the system picks the tallest layout that fits the real height.
 */
class TodayWidget : GlanceAppWidget() {
    override val sizeMode: SizeMode = SizeMode.Responsive(sizedHeights().map { DpSize(SIZED_WIDTH, it.dp) }.toSet())

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val first = readState(context)
        provideContent {
            // A redraw while a session is already running only recomposes it: provideGlance does not run again. So the
            // state is read inside the composition, again whenever [TodayWidgetBus] counts a change.
            val revision by TodayWidgetBus.revision.collectAsState()
            val read by produceState(first, revision) { value = readState(context) }
            TodayContent(read.state, read.at, read.locale)
        }
    }

    private suspend fun readState(context: Context): Read = withContext(Dispatchers.IO) {
        Read(SidekickRuntime.get(context).today.state(), System.currentTimeMillis(), WidgetLocaleStore(context).get())
    }

    private class Read(val state: TodayState, val at: Long, val locale: String)
}

/** Counts changes of what the widget shows, so a running Glance session reads the stored Today again. */
internal object TodayWidgetBus {
    val revision = MutableStateFlow(0L)

    fun changed() {
        revision.update { it + 1 }
    }
}

@Composable
private fun TodayContent(state: TodayState, now: Long, locale: String) {
    val context = WidgetLocale.localized(LocalContext.current, locale)
    Column(
        modifier = GlanceModifier
            .fillMaxSize()
            .appWidgetBackground()
            .background(Palette.background)
            .cornerRadius(20.dp)
            .padding(PADDING),
    ) {
        // Not paired: no header, the whole widget is the message and its button (there is nothing to refresh or open).
        if (state is TodayState.NotPaired) {
            NotPaired(context)
        } else {
            Header(state, context)
            when (state) {
                TodayState.Loading -> Message(context.getString(R.string.widget_loading), null)

                is TodayState.Ready ->
                    if (state.snapshot.tasks.isEmpty()) {
                        Message(
                            context.getString(R.string.widget_empty),
                            state.snapshot.notice?.let { noticeText(context, it) } ?: syncedText(context, state.snapshot, now),
                        )
                    } else {
                        Rows(state, now, context)
                    }

                TodayState.NotPaired -> Unit
            }
        }
    }
}

@Composable
private fun Header(state: TodayState, context: Context) {
    Row(
        modifier = GlanceModifier.fillMaxWidth().height(HEADER_HEIGHT),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = GlanceModifier
                .defaultWeight()
                .height(HEADER_HEIGHT)
                .clickable(actionStartActivity(DeepLinks.today(context)))
                .semantics { contentDescription = context.getString(R.string.widget_open_today) },
            contentAlignment = Alignment.CenterStart,
        ) {
            Text(
                text = context.getString(R.string.widget_title),
                style = TextStyle(color = Palette.text, fontSize = 18.sp, fontWeight = FontWeight.Bold),
                maxLines = 1,
            )
        }
        if (state !is TodayState.NotPaired) {
            Box(
                modifier = GlanceModifier
                    .size(HEADER_HEIGHT)
                    .clickable(actionRunCallback<RefreshTodayAction>())
                    .semantics { contentDescription = context.getString(R.string.widget_refresh) },
                contentAlignment = Alignment.Center,
            ) {
                Image(
                    provider = ImageProvider(R.drawable.ic_widget_refresh),
                    contentDescription = null,
                    modifier = GlanceModifier.size(20.dp),
                    colorFilter = ColorFilter.tint(Palette.muted),
                )
            }
        }
    }
}

@Composable
private fun Message(title: String, hint: String?) {
    Column(modifier = GlanceModifier.fillMaxSize(), verticalAlignment = Alignment.CenterVertically) {
        Text(text = title, style = TextStyle(color = Palette.text, fontSize = 15.sp, fontWeight = FontWeight.Medium))
        if (hint != null) {
            Spacer(GlanceModifier.height(2.dp))
            Text(text = hint, style = TextStyle(color = Palette.muted, fontSize = 13.sp))
        }
    }
}

/** The unpaired widget: a centred title and sentence over a button that opens the app, whose pairing screen is first. */
@Composable
private fun NotPaired(context: Context) {
    val open = actionStartActivity(DeepLinks.today(context))
    Column(
        modifier = GlanceModifier.fillMaxSize().clickable(open),
        verticalAlignment = Alignment.CenterVertically,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = context.getString(R.string.widget_not_paired),
            style = TextStyle(
                color = Palette.text,
                fontSize = 15.sp,
                fontWeight = FontWeight.Medium,
                textAlign = TextAlign.Center,
            ),
            maxLines = 1,
        )
        Text(
            text = context.getString(R.string.widget_not_paired_hint),
            style = TextStyle(color = Palette.muted, fontSize = 13.sp, textAlign = TextAlign.Center),
            maxLines = 1,
        )
        Spacer(GlanceModifier.height(6.dp))
        Button(
            text = context.getString(R.string.widget_pair_button),
            onClick = open,
            colors = ButtonDefaults.buttonColors(backgroundColor = Palette.primary, contentColor = Palette.onPrimary),
            maxLines = 1,
        )
    }
}

@Composable
private fun ColumnScope.Rows(state: TodayState.Ready, now: Long, context: Context) {
    val snapshot = state.snapshot
    val notice = snapshot.notice
    val layout = layoutRows(LocalSize.current.height.value, withNotice = notice != null, snapshot.tasks.size, snapshot.total)
    val shown = snapshot.tasks.take(layout.rows)
    // The server counted Today; "+N till" is its total less what is drawn, also rows that were never read.
    val hidden = layout.hidden

    // The system picks one of the declared heights, so the real widget is up to a row taller than the layout it draws
    // (or the launcher reported less than it has). When the list fills the layout the rows share that rest instead of
    // leaving a gap above "+N till"; a short list keeps its row height.
    val stretch = stretchesRows(shown.size, layout.rows)
    Column(modifier = GlanceModifier.fillMaxWidth().defaultWeight()) {
        for (task in shown) {
            val rowState = when {
                task.id in state.undoTaskIds -> RowState.UNDO
                task.id in state.pendingTaskIds -> RowState.PENDING
                else -> RowState.OPEN
            }
            TaskRow(task, rowState, stretch = stretch, context = context)
        }
    }
    if (notice != null) {
        Text(
            text = noticeText(context, notice),
            style = TextStyle(color = Palette.overdue, fontSize = 12.sp),
            maxLines = 1,
            modifier = GlanceModifier.fillMaxWidth().height(FOOTER_HEIGHT),
        )
    }
    Row(
        modifier = GlanceModifier.fillMaxWidth().height(if (hidden > 0) MORE_FOOTER_HEIGHT else FOOTER_HEIGHT),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (hidden > 0) {
            // Tapping "+N till" opens Today, where the rest of the list is: the whole footer height is the target.
            Box(
                modifier = GlanceModifier
                    .defaultWeight()
                    .fillMaxHeight()
                    .clickable(actionStartActivity(DeepLinks.today(context))),
                contentAlignment = Alignment.CenterStart,
            ) {
                Text(
                    text = context.getString(R.string.widget_more, hidden),
                    style = TextStyle(color = Palette.primary, fontSize = 12.sp, fontWeight = FontWeight.Medium),
                    maxLines = 1,
                )
            }
        } else {
            Spacer(GlanceModifier.defaultWeight())
        }
        Text(
            text = syncedText(context, snapshot, now),
            style = TextStyle(color = Palette.muted, fontSize = 12.sp),
            maxLines = 1,
        )
    }
}

/** How a row is drawn: open (the circle completes it), waiting for Undo, or completed and on its way to the server. */
private enum class RowState { OPEN, UNDO, PENDING }

@Composable
private fun ColumnScope.TaskRow(task: TodayTask, state: RowState, stretch: Boolean, context: Context) {
    val rowModifier = GlanceModifier.fillMaxWidth()
    val sized = if (stretch) rowModifier.defaultWeight() else rowModifier.height(ROW_HEIGHT)
    if (state == RowState.UNDO) {
        UndoRow(task, sized, context)
        return
    }
    val pending = state == RowState.PENDING
    val titleColor = when {
        pending -> Palette.muted
        task.overdue -> Palette.overdue
        else -> Palette.text
    }
    Row(modifier = sized, verticalAlignment = Alignment.CenterVertically) {
        val circle = GlanceModifier.size(ROW_HEIGHT)
        Box(
            modifier = if (pending) {
                circle
            } else {
                circle.clickable(actionRunCallback<CompleteTaskAction>(actionParametersOf(TASK_ID to task.id)))
            }.semantics {
                contentDescription = if (pending) {
                    context.getString(R.string.widget_pending_description, task.title)
                } else {
                    context.getString(R.string.widget_complete, task.title)
                }
            },
            contentAlignment = Alignment.Center,
        ) {
            Image(
                provider = ImageProvider(if (pending) R.drawable.ic_widget_pending else R.drawable.ic_widget_circle),
                contentDescription = null,
                modifier = GlanceModifier.size(24.dp),
                colorFilter = ColorFilter.tint(if (pending) Palette.muted else Palette.line),
            )
        }
        Row(
            modifier = GlanceModifier
                .defaultWeight()
                .fillMaxHeight()
                .clickable(actionStartActivity(DeepLinks.task(context, task.id)))
                .semantics { contentDescription = context.getString(R.string.widget_open_task, task.title) },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = task.title,
                style = TextStyle(color = titleColor, fontSize = 14.sp),
                maxLines = 1,
                modifier = GlanceModifier.defaultWeight(),
            )
            val label = when {
                pending -> context.getString(R.string.widget_pending)
                task.overdue -> context.getString(R.string.widget_overdue)
                else -> null
            }
            if (label != null) {
                Spacer(GlanceModifier.width(6.dp))
                Text(
                    text = label,
                    style = TextStyle(color = if (pending) Palette.muted else Palette.overdue, fontSize = 11.sp),
                    maxLines = 1,
                )
            }
        }
    }
}

/**
 * A row just ticked, inside its undo window: the title struck through over "Klar · Ångra". The whole row is the Undo
 * target (at least [ROW_HEIGHT] tall and as wide as the widget); the completion has not been sent, and Undo only takes it
 * out of the outbox.
 */
@Composable
private fun UndoRow(task: TodayTask, modifier: GlanceModifier, context: Context) {
    Row(
        modifier = modifier
            .clickable(actionRunCallback<UndoCompletionAction>(actionParametersOf(TASK_ID to task.id)))
            .semantics { contentDescription = context.getString(R.string.widget_undo_description, task.title) },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(modifier = GlanceModifier.size(ROW_HEIGHT), contentAlignment = Alignment.Center) {
            Image(
                provider = ImageProvider(R.drawable.ic_widget_check),
                contentDescription = null,
                modifier = GlanceModifier.size(24.dp),
                colorFilter = ColorFilter.tint(Palette.muted),
            )
        }
        Column(modifier = GlanceModifier.defaultWeight(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = task.title,
                style = TextStyle(color = Palette.muted, fontSize = 14.sp, textDecoration = TextDecoration.LineThrough),
                maxLines = 1,
            )
            Text(
                text = context.getString(R.string.widget_done_undo),
                style = TextStyle(color = Palette.primary, fontSize = 12.sp, fontWeight = FontWeight.Medium),
                maxLines = 1,
            )
        }
    }
}

/** The footer line for a [notice]. Fixed texts: nothing of the task (its title, its id) is in them. */
internal fun noticeText(context: Context, notice: TodayNotice): String = context.getString(noticeTextRes(notice))

internal fun noticeTextRes(notice: TodayNotice): Int = when (notice) {
    TodayNotice.CONFLICT -> R.string.widget_notice_conflict
    TodayNotice.REJECTED -> R.string.widget_notice_rejected
    TodayNotice.EXPIRED -> R.string.widget_notice_expired
}

/** What a height draws: [rows] whole rows, and [hidden] tasks that "+N till" stands for (0: the footer is a plain line). */
internal class RowLayout(val rows: Int, val hidden: Int)

/**
 * The rows for a [heightDp] and how many tasks are left over. "+N till" is a touch target and so makes the footer
 * [MORE_FOOTER_HEIGHT] tall instead of [FOOTER_HEIGHT]; that takes room from the rows, so the footer is only that tall
 * when something is hidden even with the plain one. [total] is the server's count of Today, [taskCount] what is cached.
 */
internal fun layoutRows(heightDp: Float, withNotice: Boolean, taskCount: Int, total: Int): RowLayout {
    val plain = rowsForHeight(heightDp, withNotice, withMore = false)
    if (total - minOf(taskCount, plain) <= 0) return RowLayout(plain, 0)
    val rows = rowsForHeight(heightDp, withNotice, withMore = true)
    return RowLayout(rows, (total - minOf(taskCount, rows)).coerceAtLeast(0))
}

/** Whether the rows share the height left over: when the tasks fill every row the layout has room for. */
internal fun stretchesRows(taskCount: Int, rowsThatFit: Int): Boolean = taskCount >= rowsThatFit

/**
 * As many whole rows as the height holds after the header, the footer ([withMore]: the tall one that holds "+N till")
 * and (when shown) the notice line; never fewer than one. No upper limit.
 */
internal fun rowsForHeight(heightDp: Float, withNotice: Boolean, withMore: Boolean = false): Int {
    var free = heightDp - CHROME_HEIGHT.value
    if (withNotice) free -= FOOTER_HEIGHT.value
    if (withMore) free -= (MORE_FOOTER_HEIGHT - FOOTER_HEIGHT).value
    return (free / ROW_HEIGHT.value).toInt().coerceAtLeast(MIN_ROWS)
}

/** "Synced 14:32", or "Offline · synced 14:32" when the last read did not get through (the time is then the last one that did). */
private fun syncedText(context: Context, snapshot: TodaySnapshot, now: Long): String {
    val sameDay = DateUtils.isToday(snapshot.syncedAtMillis) || snapshot.syncedAtMillis > now
    val flags = if (sameDay) {
        DateUtils.FORMAT_SHOW_TIME
    } else {
        DateUtils.FORMAT_SHOW_TIME or DateUtils.FORMAT_SHOW_DATE or DateUtils.FORMAT_ABBREV_ALL
    }
    val res = if (snapshot.offline) R.string.widget_offline_synced else R.string.widget_synced
    return context.getString(res, DateUtils.formatDateTime(context, snapshot.syncedAtMillis, flags))
}
