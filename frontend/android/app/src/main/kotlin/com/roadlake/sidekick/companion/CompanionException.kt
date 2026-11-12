package com.roadlake.sidekick.companion

/**
 * A refusal or failure with a closed, content-free code. The code is what JavaScript sees (the Capacitor error code)
 * and the only thing that may reach a log: never a path, a title, a token or a response body.
 *
 * Codes the native side raises itself: `not_paired`, `already_paired`, `invalid_server_url`, `invalid_pairing_secret`,
 * `path_refused`, `bad_request`, `network`, `timeout`, `redirect_refused`, `response_too_large`, `secure_storage`, `previous_data_not_removed`.
 * A failed pairing exchange carries the server's own closed error code (`pairing_invalid`, `rate_limited`, ...).
 *
 * [beforeSend] is true only when the failure provably happened before a single byte of the request was sent (no route,
 * unknown host, connection refused), so the server cannot have acted on it. The code is unchanged.
 *
 * [generation] is set only by the plugin's `request` on a failure with no answer: the pairing generation the request began
 * under, handed to the page so that a purchase it queues afterwards is bound to that pairing (see `queuePurchase`).
 */
class CompanionException(val code: String, val beforeSend: Boolean = false, val generation: Long? = null) : Exception(code)
