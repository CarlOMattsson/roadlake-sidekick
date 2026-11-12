package com.roadlake.sidekick

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.roadlake.sidekick.companion.CompanionClient
import com.roadlake.sidekick.companion.CompanionResponse
import com.roadlake.sidekick.companion.KeystorePairingStore
import com.roadlake.sidekick.companion.OwnerZone
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.companion.RenewalApi
import com.roadlake.sidekick.companion.TokenRenewal
import com.roadlake.sidekick.companion.UrlConnectionTransport
import com.roadlake.sidekick.companion.networkCheck
import com.roadlake.sidekick.push.AndroidNotificationGate
import com.roadlake.sidekick.push.AndroidReminderDisplay
import com.roadlake.sidekick.push.AndroidReminderTexts
import com.roadlake.sidekick.push.ForegroundActivity
import com.roadlake.sidekick.push.PermissionState
import com.roadlake.sidekick.push.PreferencesUnackedStore
import com.roadlake.sidekick.push.PushApi
import com.roadlake.sidekick.push.PushRegistrar
import com.roadlake.sidekick.push.PushState
import com.roadlake.sidekick.push.PushSync
import com.roadlake.sidekick.push.ReminderFlow
import com.roadlake.sidekick.push.ReminderSync
import com.roadlake.sidekick.push.RemindersApi
import com.roadlake.sidekick.push.UnifiedPushDistributor
import com.roadlake.sidekick.today.ClearingPairingStore
import com.roadlake.sidekick.today.FileTextStore
import com.roadlake.sidekick.today.OfflineReads
import com.roadlake.sidekick.today.Outbox
import com.roadlake.sidekick.today.TodayCache
import com.roadlake.sidekick.today.TodayRepository
import com.roadlake.sidekick.today.runAllOrThrow
import com.roadlake.sidekick.widget.TodaySync
import java.io.File
import java.util.TimeZone
import java.util.concurrent.CopyOnWriteArraySet

/**
 * The one set of native objects the page (the Capacitor plugin) and the widget (its callbacks and workers) share: one
 * [CompanionClient] over the Keystore pairing, and one Today cache and outbox. They must be one set: the outbox
 * serializes the completions of the app and the widget, and a 401 seen by either clears what both show.
 *
 * The push registration ([push]) is one more object of the set: it needs the same client for its two routes, and it is
 * cleared at every end of a pairing together with the cache. So are the visible reminders ([reminders]: notifications
 * on screen, ids awaiting acknowledgement), the renewal's retry note, and the queued background work of the old pairing.
 * Work that is already running when a pairing ends is cut off by one shared [PairingGeneration], which the client and
 * every flow of the set receive.
 *
 * The offline copy of the shopping lists ([offlineReads]) is one more piece of the pairing's local data, cleared with
 * the cache.
 *
 * Cache and outbox live in the no-backup directory: they follow the pairing credential's rule of never leaving the
 * phone (ADR-005).
 */
class SidekickRuntime private constructor(context: Context) {
    private val appContext = context.applicationContext
    private val pairingLostListeners = CopyOnWriteArraySet<() -> Unit>()
    private val generation = PairingGeneration()

    private fun textStore(name: String) = FileTextStore(
        File(appContext.noBackupFilesDir, "today/$name"),
        onDeleteFailure = { Log.w("SidekickStore", it) },
    )

    private val cache = TodayCache(textStore("today-cache.json"))
    private val outbox = Outbox(
        textStore("outbox.json"),
        onQuarantine = { Log.w("SidekickOutbox", "outbox file could not be parsed; moved aside") },
        clock = System::currentTimeMillis,
    )

    private val pairings = ClearingPairingStore(
        delegate = KeystorePairingStore(appContext),
        // Every step is proven or throws (and none stops the others): a new pairing is refused until all of them succeed.
        clearLocalData = {
            runAllOrThrow(
                cache::erase,
                outbox::erase,
                offlineReads::erase,
                push::clearLocal,
                renewal::clearLocal,
                reminders::clearLocal,
                { TodaySync.cancelQueued(appContext) },
                { ReminderSync.cancel(appContext) },
                { PushSync.cancel(appContext) },
            )
        },
        changed = { TodaySync.onPairingChanged(appContext) },
        generation = generation,
        onLost = { pairingLostListeners.forEach { it() } },
        onFailure = { Log.w("SidekickPairing", it) },
        marker = textStore("pairing-disconnected"),
    )

    val client: CompanionClient = CompanionClient(
        store = pairings,
        http = UrlConnectionTransport(hasNetwork = networkCheck(appContext)),
        allowLocalCleartext = BuildConfig.DEBUG,
        onPairingLost = { pairingLostListeners.forEach { it() } },
        onBeforeUnpair = { push.beforeUnpair() },
        generation = generation,
    )

    /**
     * Replaces the device credential once its `renew_after` has come. It stores through [pairings] so that renewing keeps
     * the cache and the outbox (`update`, not `save`). Run by the sync worker, which starts at app start/resume and
     * every 30 minutes for the widget.
     */
    val renewal: TokenRenewal = TokenRenewal(
        store = pairings,
        api = RenewalApi { client.renew() },
        retryState = FileTextStore(File(appContext.noBackupFilesDir, "companion/renewal.json")),
        generation = generation,
        now = System::currentTimeMillis,
    )

    /** The activity in the foreground: the distributor picker and the notification question need one. */
    val foreground = ForegroundActivity()

    private val notificationGate = AndroidNotificationGate(appContext, foreground)

    val push: PushRegistrar = PushRegistrar(
        api = object : PushApi {
            override fun put(endpoint: String): CompanionResponse = client.putPushSubscription(endpoint)

            override fun delete(): CompanionResponse = client.deletePushSubscription()
        },
        state = PushState(FileTextStore(File(appContext.noBackupFilesDir, "push/push-state.json"))),
        isPaired = { pairings.load() != null },
        distributor = UnifiedPushDistributor(appContext, foreground),
        notifications = notificationGate,
        generation = generation,
    )

    /** The visible reminders: fetched, shown in the app's language, acknowledged (D-078). */
    val reminders: ReminderFlow = ReminderFlow(
        api = object : RemindersApi {
            override fun pending(): CompanionResponse = client.pendingReminders()

            override fun ack(ids: List<String>): CompanionResponse = client.ackReminders(ids)
        },
        permitted = { notificationGate.state() == PermissionState.GRANTED },
        display = AndroidReminderDisplay(appContext),
        texts = { AndroidReminderTexts(appContext) },
        deviceZone = { OwnerZone.zoneOf(client.status().ownerTimeZone, TimeZone.getDefault()) },
        unacked = PreferencesUnackedStore(appContext),
        generation = generation,
    )

    /**
     * At start and after pairing: ask for the distributor's endpoint and the notification permission (once), and queue
     * the server registration when it is not in step. On the main thread, where the library's picker and the permission
     * question are shown.
     */
    fun ensurePush() {
        Handler(Looper.getMainLooper()).post {
            if (push.ensure()) PushSync.schedule(appContext)
        }
    }

    val today: TodayRepository = TodayRepository(client, cache, outbox, System::currentTimeMillis, generation = generation)

    /** The page's requests, with the offline copy of the shopping lists kept and used ([OfflineReads]). */
    val offlineReads: OfflineReads =
        OfflineReads(client, textStore("shopping-copy.json"), System::currentTimeMillis, generation)

    private val outboxListeners = CopyOnWriteArraySet<() -> Unit>()

    /** The page hears when a run of the queue has ended, so it can read again what was sent. */
    fun addOutboxListener(listener: () -> Unit) = outboxListeners.add(listener)

    fun removeOutboxListener(listener: () -> Unit) = outboxListeners.remove(listener)

    /** Called by the sync worker after every run. */
    fun outboxRan() = outboxListeners.forEach { it() }

    /** The page hears about a 401 seen anywhere, the widget's background work included. */
    fun addPairingLostListener(listener: () -> Unit) = pairingLostListeners.add(listener)

    fun removePairingLostListener(listener: () -> Unit) = pairingLostListeners.remove(listener)

    init {
        // A clear that failed in an earlier run is finished now; until then the phone reads as not paired.
        pairings.retryPendingClear()
    }

    companion object {
        @Volatile
        private var instance: SidekickRuntime? = null

        fun get(context: Context): SidekickRuntime = instance ?: synchronized(this) {
            instance ?: SidekickRuntime(context).also { instance = it }
        }
    }
}
