package com.wlukaz.loseitsync

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Background job that re-syncs the last week every few hours. */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result = try {
        Syncer.sync(applicationContext, RECENT_DAYS)
        Result.success()
    } catch (e: IOException) {
        Settings(applicationContext).lastStatus = "Auto-sync failed (will retry): ${e.message}"
        Result.retry()
    } catch (e: Exception) {
        Settings(applicationContext).lastStatus = "Auto-sync failed: ${e.message}"
        Result.failure()
    }

    companion object {
        const val RECENT_DAYS = 7
        private const val WORK_NAME = "loseit-sync"

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<SyncWorker>(6, TimeUnit.HOURS)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(WORK_NAME, ExistingPeriodicWorkPolicy.UPDATE, request)
        }
    }
}
