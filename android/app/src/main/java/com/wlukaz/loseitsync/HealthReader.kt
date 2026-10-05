package com.wlukaz.loseitsync

import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.MealType
import androidx.health.connect.client.records.NutritionRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.records.metadata.DataOrigin
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.health.connect.client.units.Mass
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.roundToLong
import kotlin.reflect.KClass

/** A table of rows ready to send: column names plus one value list per record. */
class Table(val columns: List<String>, val rows: List<List<Any?>>)

/** Reads LoseIt's nutrition and weight records out of Health Connect as flat tables. */
class HealthReader(private val client: HealthConnectClient, private val zone: ZoneId = ZoneId.systemDefault()) {

    suspend fun readNutrition(from: LocalDate, to: LocalDate, sourcePackage: String): Table {
        val records = readAll(NutritionRecord::class, from, to, sourcePackage)
        val rows = records.sortedBy { it.startTime }.map { r ->
            listOf<Any?>(
                r.metadata.id,
                dateOf(r.startTime),
                timeOf(r.startTime),
                mealName(r.mealType),
                r.name,
                r.metadata.dataOrigin.packageName,
            ) + NUTRIENTS.map { it.value(r) }
        }
        return Table(NUTRITION_KEY_COLUMNS + NUTRIENTS.map { it.column }, rows)
    }

    suspend fun readWeight(from: LocalDate, to: LocalDate, sourcePackage: String): Table {
        val records = readAll(WeightRecord::class, from, to, sourcePackage)
        val rows = records.sortedBy { it.time }.map { r ->
            listOf<Any?>(
                r.metadata.id,
                dateOf(r.time),
                timeOf(r.time),
                round(r.weight.inPounds),
                round(r.weight.inKilograms),
                r.metadata.dataOrigin.packageName,
            )
        }
        return Table(listOf("id", "date", "time", "weight_lb", "weight_kg", "source"), rows)
    }

    private suspend fun <T : Record> readAll(type: KClass<T>, from: LocalDate, to: LocalDate, sourcePackage: String): List<T> {
        val filter = TimeRangeFilter.between(
            from.atStartOfDay(zone).toInstant(),
            to.plusDays(1).atStartOfDay(zone).toInstant(),
        )
        val origins = if (sourcePackage.isBlank()) emptySet() else setOf(DataOrigin(sourcePackage))
        val out = mutableListOf<T>()
        var pageToken: String? = null
        do {
            val response = client.readRecords(
                ReadRecordsRequest(
                    recordType = type,
                    timeRangeFilter = filter,
                    dataOriginFilter = origins,
                    pageSize = 1000,
                    pageToken = pageToken,
                )
            )
            out += response.records
            pageToken = response.pageToken
        } while (pageToken != null)
        return out
    }

    private fun dateOf(t: Instant) = t.atZone(zone).toLocalDate().toString()
    private fun timeOf(t: Instant) = t.atZone(zone).format(TIME_FORMAT)

    companion object {
        val BASE_PERMISSIONS = setOf(
            HealthPermission.getReadPermission(NutritionRecord::class),
            HealthPermission.getReadPermission(WeightRecord::class),
        )

        private val TIME_FORMAT = DateTimeFormatter.ofPattern("HH:mm")
        private val NUTRITION_KEY_COLUMNS = listOf("id", "date", "time", "meal", "name", "source")

        private class Nutrient(val column: String, val value: (NutritionRecord) -> Double?)

        private fun g(column: String, f: (NutritionRecord) -> Mass?) = Nutrient("${column}_g") { r -> f(r)?.inGrams?.let(::round) }
        private fun mg(column: String, f: (NutritionRecord) -> Mass?) = Nutrient("${column}_mg") { r -> f(r)?.inMilligrams?.let(::round) }
        private fun mcg(column: String, f: (NutritionRecord) -> Mass?) = Nutrient("${column}_mcg") { r -> f(r)?.inMicrograms?.let(::round) }

        /** Every nutrient field Health Connect's NutritionRecord defines, in label units. */
        private val NUTRIENTS = listOf(
            Nutrient("calories_kcal") { r -> r.energy?.inKilocalories?.let(::round) },
            Nutrient("calories_from_fat_kcal") { r -> r.energyFromFat?.inKilocalories?.let(::round) },
            g("protein") { it.protein },
            g("carbs") { it.totalCarbohydrate },
            g("fiber") { it.dietaryFiber },
            g("sugar") { it.sugar },
            g("fat") { it.totalFat },
            g("saturated_fat") { it.saturatedFat },
            g("monounsaturated_fat") { it.monounsaturatedFat },
            g("polyunsaturated_fat") { it.polyunsaturatedFat },
            g("unsaturated_fat") { it.unsaturatedFat },
            g("trans_fat") { it.transFat },
            mg("cholesterol") { it.cholesterol },
            mg("sodium") { it.sodium },
            mg("potassium") { it.potassium },
            mg("chloride") { it.chloride },
            mg("calcium") { it.calcium },
            mg("iron") { it.iron },
            mg("magnesium") { it.magnesium },
            mg("phosphorus") { it.phosphorus },
            mg("zinc") { it.zinc },
            mg("copper") { it.copper },
            mg("manganese") { it.manganese },
            mcg("selenium") { it.selenium },
            mcg("chromium") { it.chromium },
            mcg("molybdenum") { it.molybdenum },
            mcg("iodine") { it.iodine },
            mcg("vitamin_a") { it.vitaminA },
            mg("vitamin_c") { it.vitaminC },
            mcg("vitamin_d") { it.vitaminD },
            mg("vitamin_e") { it.vitaminE },
            mcg("vitamin_k") { it.vitaminK },
            mg("thiamin") { it.thiamin },
            mg("riboflavin") { it.riboflavin },
            mg("niacin") { it.niacin },
            mg("pantothenic_acid") { it.pantothenicAcid },
            mg("vitamin_b6") { it.vitaminB6 },
            mcg("biotin") { it.biotin },
            mcg("folate") { it.folate },
            mcg("folic_acid") { it.folicAcid },
            mcg("vitamin_b12") { it.vitaminB12 },
            mg("caffeine") { it.caffeine },
        )

        private fun round(v: Double): Double = (v * 1000).roundToLong() / 1000.0

        private fun mealName(type: Int) = when (type) {
            MealType.MEAL_TYPE_BREAKFAST -> "breakfast"
            MealType.MEAL_TYPE_LUNCH -> "lunch"
            MealType.MEAL_TYPE_DINNER -> "dinner"
            MealType.MEAL_TYPE_SNACK -> "snack"
            else -> ""
        }
    }
}
