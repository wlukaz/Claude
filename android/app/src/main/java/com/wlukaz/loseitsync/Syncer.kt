package com.wlukaz.loseitsync

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

object Syncer {
    /** Days per upload; keeps each Apps Script request small and well under its time limit. */
    private const val CHUNK_DAYS = 14L

    /**
     * Re-sends the last [days] days (including today). The script replaces every row in each
     * uploaded date range, so edits and deletions made in LoseIt carry through to the sheet.
     */
    suspend fun sync(context: Context, days: Int): String {
        val settings = Settings(context)
        check(settings.isConfigured) { "Enter the Apps Script URL and token, then tap Save." }

        val zone = ZoneId.systemDefault()
        val reader = HealthReader(HealthConnectClient.getOrCreate(context), zone)
        val today = LocalDate.now(zone)
        var chunkStart = today.minusDays(days.coerceAtLeast(1) - 1L)
        var foods = 0
        var weights = 0

        while (!chunkStart.isAfter(today)) {
            val chunkEnd = minOf(chunkStart.plusDays(CHUNK_DAYS - 1), today)
            val nutrition = reader.readNutrition(chunkStart, chunkEnd, settings.sourcePackage)
            val weight = reader.readWeight(chunkStart, chunkEnd, settings.sourcePackage)

            val body = JSONObject()
                .put("token", settings.token)
                .put("rangeStart", chunkStart.toString())
                .put("rangeEnd", chunkEnd.toString())
                .put("timezone", zone.id)
                .put("nutrition", tableJson(nutrition))
                .put("weight", tableJson(weight))
            withContext(Dispatchers.IO) { Uploader.post(settings.scriptUrl, body) }

            foods += nutrition.rows.size
            weights += weight.rows.size
            chunkStart = chunkEnd.plusDays(1)
        }

        val stamp = LocalDateTime.now(zone).format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))
        return "OK $stamp: $days days, $foods food entries, $weights weigh-ins".also { settings.lastStatus = it }
    }

    private fun tableJson(table: Table) = JSONObject()
        .put("columns", JSONArray(table.columns))
        .put("rows", JSONArray(table.rows.map { row -> JSONArray(row.map { it ?: JSONObject.NULL }) }))
}
