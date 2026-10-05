package com.wlukaz.loseitsync

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.ActivityResultLauncher
import androidx.appcompat.app.AppCompatActivity
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.lifecycle.lifecycleScope
import com.wlukaz.loseitsync.databinding.ActivityMainBinding
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var settings: Settings
    private lateinit var requestPermissions: ActivityResultLauncher<Set<String>>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        settings = Settings(this)

        requestPermissions = registerForActivityResult(PermissionController.createRequestPermissionResultContract()) {
            lifecycleScope.launch { showStatus() }
        }

        binding.scriptUrl.setText(settings.scriptUrl)
        binding.token.setText(settings.token)
        binding.sourcePackage.setText(settings.sourcePackage)
        binding.backfillDays.setText(settings.backfillDays.toString())

        binding.save.setOnClickListener { save() }
        binding.grant.setOnClickListener { grant() }
        binding.syncNow.setOnClickListener { runSync(SyncWorker.RECENT_DAYS) }
        binding.backfill.setOnClickListener {
            save()
            runSync(settings.backfillDays)
        }

        if (settings.isConfigured) SyncWorker.schedule(this)
    }

    override fun onResume() {
        super.onResume()
        lifecycleScope.launch { showStatus() }
    }

    private fun save() {
        settings.scriptUrl = binding.scriptUrl.text.toString()
        settings.token = binding.token.text.toString()
        settings.sourcePackage = binding.sourcePackage.text.toString()
        settings.backfillDays = binding.backfillDays.text.toString().toIntOrNull()?.coerceIn(1, 3650) ?: 30
        if (settings.isConfigured) {
            SyncWorker.schedule(this)
            toast("Saved. Auto-sync runs every 6 hours.")
        } else {
            toast("Saved, but the URL (https://…) and token are both required for auto-sync.")
        }
    }

    private fun grant() {
        when (HealthConnectClient.getSdkStatus(this)) {
            HealthConnectClient.SDK_AVAILABLE -> lifecycleScope.launch {
                val client = HealthConnectClient.getOrCreate(this@MainActivity)
                val wanted = HealthReader.BASE_PERMISSIONS.toMutableSet()
                if (featureAvailable(client, HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND)) {
                    wanted += HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND
                }
                if (featureAvailable(client, HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_HISTORY)) {
                    wanted += HealthPermission.PERMISSION_READ_HEALTH_DATA_HISTORY
                }
                requestPermissions.launch(wanted)
            }
            HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> startActivity(
                Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=com.google.android.apps.healthdata"))
            )
            else -> toast("Health Connect isn't available on this device.")
        }
    }

    private fun featureAvailable(client: HealthConnectClient, feature: Int) =
        client.features.getFeatureStatus(feature) == HealthConnectFeatures.FEATURE_STATUS_AVAILABLE

    private fun runSync(days: Int) {
        binding.status.text = "Syncing $days days…"
        lifecycleScope.launch {
            try {
                Syncer.sync(this@MainActivity, days)
            } catch (e: Exception) {
                settings.lastStatus = "Sync failed: ${e.message}"
            }
            showStatus()
        }
    }

    private suspend fun showStatus() {
        val lines = mutableListOf("Last sync: ${settings.lastStatus}")
        if (HealthConnectClient.getSdkStatus(this) == HealthConnectClient.SDK_AVAILABLE) {
            val granted = HealthConnectClient.getOrCreate(this).permissionController.getGrantedPermissions()
            lines += if (granted.containsAll(HealthReader.BASE_PERMISSIONS)) "Health Connect: nutrition + weight access granted"
            else "Health Connect: access NOT granted. Tap \"Grant Health Connect access\"."
            lines += "Background sync: " +
                if (HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND in granted) "allowed" else "not allowed (syncs only while the app is open)"
            lines += "History beyond 30 days: " +
                if (HealthPermission.PERMISSION_READ_HEALTH_DATA_HISTORY in granted) "allowed" else "not allowed"
        }
        binding.status.text = lines.joinToString("\n")
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
}
