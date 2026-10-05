package com.wlukaz.loseitsync

import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/** Shown by Health Connect when the user asks why this app wants access. */
class PrivacyActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val padding = (16 * resources.displayMetrics.density).toInt()
        setContentView(TextView(this).apply {
            setText(R.string.privacy_text)
            setPadding(padding, padding, padding, padding)
        })
    }
}
