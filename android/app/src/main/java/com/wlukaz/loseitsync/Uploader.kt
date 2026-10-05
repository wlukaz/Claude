package com.wlukaz.loseitsync

import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Posts JSON to the Apps Script web app and returns its JSON reply. Blocking; call off the main thread. */
object Uploader {

    fun post(url: String, body: JSONObject): JSONObject {
        var conn = open(url).apply {
            requestMethod = "POST"
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }
        conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }

        // Apps Script runs doPost, then answers 302 to a googleusercontent.com URL that serves the output via GET.
        var code = conn.responseCode
        var hops = 0
        while (code in 301..308 && hops < 5) {
            val location = conn.getHeaderField("Location") ?: break
            conn.disconnect()
            conn = open(location)
            code = conn.responseCode
            hops++
        }

        val text = try {
            (if (code in 200..299) conn.inputStream else conn.errorStream)?.bufferedReader()?.use { it.readText() } ?: ""
        } finally {
            conn.disconnect()
        }
        if (code !in 200..299) throw IOException("HTTP $code from Apps Script: ${text.take(300)}")

        val json = try {
            JSONObject(text)
        } catch (e: JSONException) {
            throw IllegalStateException(
                "Apps Script did not return JSON. Check the web app is deployed with \"Who has access: Anyone\". Got: ${text.take(200)}"
            )
        }
        if (!json.optBoolean("ok")) throw IllegalStateException("Apps Script error: ${json.optString("error")}")
        return json
    }

    private fun open(url: String) = (URL(url).openConnection() as HttpURLConnection).apply {
        instanceFollowRedirects = false
        connectTimeout = 30_000
        readTimeout = 180_000
    }
}
