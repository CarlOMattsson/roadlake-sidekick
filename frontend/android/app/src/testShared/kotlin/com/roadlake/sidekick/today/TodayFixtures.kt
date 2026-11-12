package com.roadlake.sidekick.today

// Shared by the JVM tests (src/test) and the instrumented tests (src/androidTest): see sourceSets in app/build.gradle.

/** A shopping list id (the add queue is keyed by list). */
const val LIST = "66666666-7777-4888-8999-000000000000"
const val TASK_A = "3f2b8c1e-4d5a-4b6c-9d7e-8f9a0b1c2d3e"
const val TASK_B = "4a3c9d2f-5e6b-4c7d-8e8f-9a0b1c2d3e4f"

/** A `GET /companion/v1/work/today` page; [total] is the server's own count, which may exceed the rows sent. */
fun todayPage(vararg items: String, total: Int = items.size, day: String = "2026-11-09"): String =
    """{"api_version":"companion.v1","day":"$day","timezone":"Europe/Stockholm","calculated_at":"2026-11-09T07:00:00Z",""" +
        """"limit":20,"total":$total,"overdue_total":0,"today_total":$total,"has_more":${total > items.size},""" +
        """"next_cursor":null,"items":[${items.joinToString(",")}]}"""

fun item(id: String, title: String, version: Int = 1, group: String = "today", extra: String = ""): String =
    """{"id":"$id","title":${org.json.JSONObject.quote(title)},"version":$version,"status":"todo","group":"$group",""" +
        """"due_at":"2026-11-08T10:00:00Z","description":"SECRET NOTE","project_title":"P"$extra}"""
