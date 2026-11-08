package com.example.aimusicstudio

import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import kotlin.random.Random

object AiSongGenerator {
    private val scales = mapOf(
        "Minor" to intArrayOf(0, 2, 3, 5, 7, 8, 10),
        "Major" to intArrayOf(0, 2, 4, 5, 7, 9, 11),
        "Pentatonic" to intArrayOf(0, 3, 5, 7, 10)
    )

    fun generateLocalAiSong(engine: SynthEngine, style: String, rootKey: Int, scaleName: String) {
        val scale = scales[scaleName] ?: scales["Minor"]!!
        for (t in 0 until SynthEngine.NUM_TRACKS) engine.grid[t].fill(0)

        when (style) {
            "Trap / Hip-Hop" -> {
                engine.bpm = 140
                intArrayOf(0, 3, 6, 10, 14).forEach { s ->
                    if (Random.nextFloat() < 0.85f) engine.grid[0][s] = 36
                }
                engine.grid[1][4] = 38; engine.grid[1][12] = 38
                for (s in 0 until 16) {
                    if (s % 2 == 0 || Random.nextFloat() < 0.45f) engine.grid[2][s] = 42
                }
                engine.grid[3][4] = 39; engine.grid[3][12] = 39
            }
            "House / Techno" -> {
                engine.bpm = 126
                for (s in 0 until 16 step 4) engine.grid[0][s] = 36
                engine.grid[1][4] = 38; engine.grid[1][12] = 38
                engine.grid[3][4] = 39; engine.grid[3][12] = 39
                for (s in 2 until 16 step 4) engine.grid[2][s] = 42
            }
            else -> {
                engine.bpm = 110
                engine.grid[0][0] = 36; engine.grid[0][6] = 36; engine.grid[0][8] = 36; engine.grid[0][14] = 36
                engine.grid[1][4] = 38; engine.grid[1][12] = 38
                for (s in 0 until 16 step 2) engine.grid[2][s] = 42
                if (Random.nextBoolean()) engine.grid[3][15] = 39
            }
        }

        val chordDegrees = intArrayOf(0, 5 % scale.size, 2 % scale.size, 6 % scale.size)
        for (barQuarter in 0 until 4) {
            val stepStart = barQuarter * 4
            val deg = chordDegrees[barQuarter]
            val noteOffset = scale[deg]

            val padMidi = engine.getTrackBaseMidi(7) + rootKey + noteOffset
            engine.grid[7][stepStart] = padMidi
            engine.grid[7][stepStart + 2] = padMidi

            val bassMidi = engine.getTrackBaseMidi(4) + rootKey + noteOffset
            engine.grid[4][stepStart] = bassMidi
            engine.grid[4][stepStart + 2] = bassMidi
            if (Random.nextFloat() < 0.5f) engine.grid[4][stepStart + 3] = bassMidi + 12

            val keysBase = engine.getTrackBaseMidi(6)
            engine.grid[6][stepStart + 1] = keysBase + rootKey + scale[(deg + 2) % scale.size]
            if (Random.nextFloat() < 0.65f) {
                engine.grid[6][stepStart + 3] = keysBase + rootKey + scale[(deg + 4) % scale.size]
            }
        }

        val leadBase = engine.getTrackBaseMidi(5)
        var currentDegree = 0
        for (s in 0 until 16) {
            if (Random.nextFloat() < 0.65f) {
                val stepMove = intArrayOf(-1, 0, 1, 2).random()
                currentDegree = (currentDegree + stepMove + scale.size) % scale.size
                val octaveShift = if (Random.nextFloat() < 0.25f) 12 else 0
                engine.grid[5][s] = leadBase + rootKey + scale[currentDegree] + octaveShift
            }
        }
    }

    fun generateCloudGeminiPattern(apiKey: String, prompt: String, engine: SynthEngine): Boolean {
        return try {
            val url = URL("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=$apiKey")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                setRequestProperty("Content-Type", "application/json")
                doOutput = true
                connectTimeout = 8000
                readTimeout = 8000
            }
            val sysPrompt = "Return ONLY raw JSON (no markdown) for an 8-track, 16-step sequencer pattern matching: " +
                prompt + ". JSON format: {\"bpm\": 124, \"grid\": [[16 ints], ... 8 arrays total]}. " +
                "Tracks 0-3 use 0 or 36. Tracks 4-7 use 0 or MIDI note 36..83."

            val payload = JSONObject().apply {
                put("contents", org.json.JSONArray().put(
                    JSONObject().put("parts", org.json.JSONArray().put(
                        JSONObject().put("text", sysPrompt)
                    ))
                ))
            }
            OutputStreamWriter(conn.outputStream).use { it.write(payload.toString()) }
            val responseText = conn.inputStream.bufferedReader().readText()
            val root = JSONObject(responseText)
            val rawText = root.getJSONArray("candidates")
                .getJSONObject(0).getJSONObject("content")
                .getJSONArray("parts").getJSONObject(0).getString("text")
                .replace("```json", "").replace("```", "").trim()

            val songJson = JSONObject(rawText)
            engine.bpm = songJson.optInt("bpm", 120).coerceIn(60, 200)
            val gridJson = songJson.getJSONArray("grid")
            for (t in 0 until minOf(8, gridJson.length())) {
                val row = gridJson.getJSONArray(t)
                for (s in 0 until minOf(16, row.length())) {
                    engine.grid[t][s] = row.getInt(s)
                }
            }
            true
        } catch (e: Exception) {
            false
        }
    }
}
