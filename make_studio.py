import os

PROJECT_FILES = {
    ".github/workflows/build.yml": """name: Build AI Music Studio APK
on:
  push:
    branches: [ "main", "master" ]
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
      - name: Setup JDK 17
        uses: actions/setup-java@v4
        with:
          java-version: '17'
          distribution: 'temurin'
      - name: Setup Gradle
        uses: gradle/actions/setup-gradle@v4
        with:
          gradle-version: '8.7'
      - name: Compile Debug APK
        run: gradle assembleDebug --no-daemon
      - name: Upload Compiled Studio APK
        uses: actions/upload-artifact@v4
        with:
          name: ai-music-studio-apk
          path: app/build/outputs/apk/debug/*.apk
""",
    "settings.gradle.kts": """pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "AIMusicStudio"
include(":app")
""",
    "build.gradle.kts": """plugins {
    id("com.android.application") version "8.3.0" apply false
    id("org.jetbrains.kotlin.android") version "1.9.22" apply false
}
""",
    "gradle.properties": """android.useAndroidX=true
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
""",
    "app/build.gradle.kts": """plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.example.aimusicstudio"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.example.aimusicstudio"
        minSdk = 24
        targetSdk = 34
        versionCode = 2
        versionName = "2.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")
}
""",
    "app/src/main/AndroidManifest.xml": """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.INTERNET" />
    <application
        android:allowBackup="true"
        android:label="AI Studio DAW"
        android:supportsRtl="true"
        android:theme="@style/Theme.AppCompat.NoActionBar">
        <activity
            android:name=".MainActivity"
            android:screenOrientation="sensorLandscape"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
""",
    "app/src/main/java/com/example/aimusicstudio/SynthEngine.kt": """package com.example.aimusicstudio

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.Environment
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.concurrent.thread
import kotlin.math.*
import kotlin.random.Random

class SynthEngine {
    companion object {
        const val SAMPLE_RATE = 44100
        const val NUM_TRACKS = 8
        const val NUM_STEPS = 16
        val TRACK_NAMES = arrayOf(
            "Kick", "Snare", "Hi-Hat", "Clap",
            "Sub Bass", "Saw Lead", "FM Keys", "Warm Pad"
        )
    }

    val grid = Array(NUM_TRACKS) { IntArray(NUM_STEPS) { 0 } }
    val trackMuted = BooleanArray(NUM_TRACKS) { false }

    @Volatile var isPlaying = false
    @Volatile var bpm = 120
    @Volatile var currentStep = 0
    var onStepChanged: ((Int) -> Unit)? = null

    private var audioThread: Thread? = null

    fun start() {
        if (isPlaying) return
        isPlaying = true
        audioThread = thread(start = true, name = "DAWAudioThread") { runAudioLoop() }
    }

    fun stop() {
        isPlaying = false
        audioThread?.join(500)
        audioThread = null
    }

    fun midiToFreq(midi: Int): Double = 440.0 * 2.0.pow((midi - 69) / 12.0)

    fun getTrackBaseMidi(track: Int): Int = when (track) {
        4 -> 36
        5 -> 60
        6 -> 53
        7 -> 48
        else -> 36
    }

    fun triggerNotePreview(track: Int, midiNote: Int) {
        thread(start = true, name = "NotePreview") {
            val numSamples = (SAMPLE_RATE * 0.22).toInt()
            val previewBuf = ShortArray(numSamples)
            val active = IntArray(NUM_TRACKS) { 0 }
            active[track] = midiNote
            renderNotesToBuffer(active, previewBuf, numSamples)

            val minBuf = AudioTrack.getMinBufferSize(
                SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            val trackOut = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(SAMPLE_RATE)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build()
                )
                .setBufferSizeInBytes(max(minBuf, previewBuf.size * 2))
                .setTransferMode(AudioTrack.MODE_STATIC)
                .build()

            trackOut.write(previewBuf, 0, previewBuf.size)
            trackOut.play()
            Thread.sleep(240)
            trackOut.stop()
            trackOut.release()
        }
    }

    private fun runAudioLoop() {
        val minBuf = AudioTrack.getMinBufferSize(
            SAMPLE_RATE, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        val audioTrack = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(max(minBuf, 4096))
            .build()

        audioTrack.play()
        var stepIdx = 0

        while (isPlaying) {
            currentStep = stepIdx
            onStepChanged?.invoke(stepIdx)
            val samplesPerStep = (SAMPLE_RATE * 60.0 / bpm / 4.0).toInt()
            val stepBuffer = renderStepSamples(stepIdx, samplesPerStep)
            audioTrack.write(stepBuffer, 0, stepBuffer.size)
            stepIdx = (stepIdx + 1) % NUM_STEPS
        }

        audioTrack.stop()
        audioTrack.release()
    }

    fun renderStepSamples(stepIdx: Int, numSamples: Int): ShortArray {
        val out = ShortArray(numSamples)
        val activeNotes = IntArray(NUM_TRACKS) { t ->
            if (trackMuted[t]) 0 else grid[t][stepIdx]
        }
        renderNotesToBuffer(activeNotes, out, numSamples)
        return out
    }

    private fun renderNotesToBuffer(activeNotes: IntArray, out: ShortArray, numSamples: Int) {
        for (i in 0 until numSamples) {
            val t = i.toDouble() / SAMPLE_RATE
            val progress = i.toDouble() / numSamples
            var mix = 0.0

            if (activeNotes[0] > 0) {
                val env = exp(-t * 18.0)
                val freq = 140.0 * exp(-t * 32.0) + 42.0
                mix += sin(2.0 * PI * freq * t) * env * 0.9
            }
            if (activeNotes[1] > 0) {
                val noiseEnv = exp(-t * 26.0)
                val bodyEnv = exp(-t * 40.0)
                val noise = (Random.nextDouble() * 2.0 - 1.0) * noiseEnv * 0.55
                val body = sin(2.0 * PI * 185.0 * t) * bodyEnv * 0.45
                mix += (noise + body)
            }
            if (activeNotes[2] > 0) {
                val env = exp(-t * 65.0)
                val metallic = sin(2.0 * PI * 6400.0 * t) * sin(2.0 * PI * 9100.0 * t)
                val noise = (Random.nextDouble() * 2.0 - 1.0)
                mix += (noise * 0.7 + metallic * 0.3) * env * 0.45
            }
            if (activeNotes[3] > 0) {
                val retrigger = if (t < 0.012 || (t > 0.018 && t < 0.028)) 1.0 else exp(-t * 24.0)
                val noise = (Random.nextDouble() * 2.0 - 1.0) * retrigger
                mix += noise * 0.5
            }
            if (activeNotes[4] > 0) {
                val freq = midiToFreq(activeNotes[4])
                val env = (1.0 - progress).pow(0.6)
                val fundamental = sin(2.0 * PI * freq * t)
                val subHarmonic = if (sin(2.0 * PI * (freq * 0.5) * t) >= 0) 0.25 else -0.25
                mix += tanh((fundamental + subHarmonic) * 1.6) * env * 0.55
            }
            if (activeNotes[5] > 0) {
                val freq = midiToFreq(activeNotes[5])
                val env = exp(-t * 6.5)
                val saw1 = 2.0 * (t * freq - floor(0.5 + t * freq))
                val saw2 = 2.0 * (t * (freq * 1.006) - floor(0.5 + t * (freq * 1.006)))
                mix += (saw1 + saw2) * 0.5 * env * 0.38
            }
            if (activeNotes[6] > 0) {
                val freq = midiToFreq(activeNotes[6])
                val modEnv = exp(-t * 14.0)
                val ampEnv = exp(-t * 5.0)
                val modulator = sin(2.0 * PI * (freq * 2.0) * t) * 2.5 * modEnv
                val carrier = sin(2.0 * PI * freq * t + modulator)
                mix += carrier * ampEnv * 0.42
            }
            if (activeNotes[7] > 0) {
                val root = midiToFreq(activeNotes[7])
                val fifth = midiToFreq(activeNotes[7] + 7)
                val attackRelease = sin(PI * progress)
                val chord = (sin(2.0 * PI * root * t) +
                             sin(2.0 * PI * fifth * t) * 0.7 +
                             sin(2.0 * PI * (root * 2.0) * t) * 0.4) / 2.1
                mix += chord * attackRelease * 0.40
            }

            val limited = tanh(mix * 0.85)
            out[i] = (limited * 32760.0).toInt().coerceIn(-32768, 32767).toShort()
        }
    }

    fun exportWavFile(context: Context, bars: Int = 2): File {
        val samplesPerStep = (SAMPLE_RATE * 60.0 / bpm / 4.0).toInt()
        val totalSteps = NUM_STEPS * bars
        val totalSamples = samplesPerStep * totalSteps
        val pcmData = ShortArray(totalSamples)

        var offset = 0
        for (s in 0 until totalSteps) {
            val stepSamples = renderStepSamples(s % NUM_STEPS, samplesPerStep)
            System.arraycopy(stepSamples, 0, pcmData, offset, samplesPerStep)
            offset += samplesPerStep
        }

        val musicDir = context.getExternalFilesDir(Environment.DIRECTORY_MUSIC) ?: context.filesDir
        val outFile = File(musicDir, "AI_Studio_Track_${System.currentTimeMillis()}.wav")

        FileOutputStream(outFile).use { fos ->
            val byteDataSize = totalSamples * 2
            val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
            header.put("RIFF".toByteArray())
            header.putInt(36 + byteDataSize)
            header.put("WAVE".toByteArray())
            header.put("fmt ".toByteArray())
            header.putInt(16)
            header.putShort(1)
            header.putShort(1)
            header.putInt(SAMPLE_RATE)
            header.putInt(SAMPLE_RATE * 2)
            header.putShort(2)
            header.putShort(16)
            header.put("data".toByteArray())
            header.putInt(byteDataSize)
            fos.write(header.array())

            val pcmBuffer = ByteBuffer.allocate(byteDataSize).order(ByteOrder.LITTLE_ENDIAN)
            for (sample in pcmData) {
                pcmBuffer.putShort(sample)
            }
            fos.write(pcmBuffer.array())
        }
        return outFile
    }
}
""",
    "app/src/main/java/com/example/aimusicstudio/AutoTuneProcessor.kt": """package com.example.aimusicstudio

import android.annotation.SuppressLint
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import kotlin.concurrent.thread
import kotlin.math.*

class AutoTuneProcessor {
    @Volatile var isRunning = false
    @Volatile var retuneSpeed = 0.85f
    @Volatile var rootKey = 0
    @Volatile var scaleType = "Minor"
    var onPitchDetected: ((String, Int, Int) -> Unit)? = null

    private val noteNames = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    private var workerThread: Thread? = null

    private val scales = mapOf(
        "Major" to intArrayOf(0, 2, 4, 5, 7, 9, 11),
        "Minor" to intArrayOf(0, 2, 3, 5, 7, 8, 10),
        "Pentatonic" to intArrayOf(0, 3, 5, 7, 10),
        "Chromatic" to intArrayOf(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
    )

    @SuppressLint("MissingPermission")
    fun start() {
        if (isRunning) return
        isRunning = true
        workerThread = thread(start = true, name = "AutoTuneDSP") {
            val sr = 44100
            val frameSize = 1024
            val minRecBuf = AudioRecord.getMinBufferSize(
                sr, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            val recorder = AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION, sr,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                max(minRecBuf, frameSize * 4)
            )
            val minPlayBuf = AudioTrack.getMinBufferSize(
                sr, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
            )
            val player = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(sr)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build()
                )
                .setBufferSizeInBytes(max(minPlayBuf, frameSize * 4))
                .build()

            val inBuf = ShortArray(frameSize)
            val outBuf = ShortArray(frameSize)
            var smoothedRatio = 1.0
            var readPhase = 0.0
            val ringSize = frameSize * 4
            val ringBuffer = ShortArray(ringSize)
            var writePos = 0

            recorder.startRecording()
            player.play()

            while (isRunning) {
                val read = recorder.read(inBuf, 0, frameSize)
                if (read <= 0) continue
                for (i in 0 until read) {
                    ringBuffer[(writePos + i) % ringSize] = inBuf[i]
                }
                val detectedFreq = detectPitchAutocorrelation(inBuf, read, sr)
                var targetRatio = 1.0
                if (detectedFreq in 75.0..900.0) {
                    val detectedMidi = 69.0 + 12.0 * log2(detectedFreq / 440.0)
                    val targetMidi = snapToScale(detectedMidi.roundToInt())
                    val targetFreq = 440.0 * 2.0.pow((targetMidi - 69) / 12.0)
                    targetRatio = (targetFreq / detectedFreq).coerceIn(0.5, 2.0)
                    val noteStr = noteNames[targetMidi % 12] + (targetMidi / 12 - 1)
                    onPitchDetected?.invoke(noteStr, detectedFreq.roundToInt(), targetFreq.roundToInt())
                } else {
                    onPitchDetected?.invoke("--", 0, 0)
                }
                smoothedRatio += (targetRatio - smoothedRatio) * retuneSpeed
                for (i in 0 until read) {
                    val idx0 = readPhase.toInt() % ringSize
                    val idx1 = (idx0 + 1) % ringSize
                    val frac = readPhase - floor(readPhase)
                    val s0 = ringBuffer[if (idx0 < 0) idx0 + ringSize else idx0]
                    val s1 = ringBuffer[if (idx1 < 0) idx1 + ringSize else idx1]
                    outBuf[i] = (s0 + frac * (s1 - s0)).toInt().coerceIn(-32768, 32767).toShort()
                    readPhase = (readPhase + smoothedRatio) % ringSize
                }
                writePos = (writePos + read) % ringSize
                player.write(outBuf, 0, read)
            }
            recorder.stop()
            recorder.release()
            player.stop()
            player.release()
        }
    }

    fun stop() {
        isRunning = false
        workerThread?.join(400)
        workerThread = null
    }

    private fun snapToScale(midiNote: Int): Int {
        val allowedIntervals = scales[scaleType] ?: scales["Minor"]!!
        val octave = midiNote / 12
        val relPitch = (midiNote % 12 - rootKey + 12) % 12
        var bestInterval = allowedIntervals[0]
        var minDiff = 99
        for (interval in allowedIntervals) {
            val diff = abs(relPitch - interval)
            if (diff < minDiff) {
                minDiff = diff
                bestInterval = interval
            }
        }
        return octave * 12 + ((rootKey + bestInterval) % 12)
    }

    private fun detectPitchAutocorrelation(buffer: ShortArray, length: Int, sampleRate: Int): Double {
        var rms = 0.0
        for (i in 0 until length) {
            val v = buffer[i] / 32768.0
            rms += v * v
        }
        rms = sqrt(rms / length)
        if (rms < 0.015) return -1.0
        val minLag = sampleRate / 900
        val maxLag = min(length / 2, sampleRate / 75)
        var bestLag = -1
        var maxCorr = 0.0
        for (lag in minLag..maxLag) {
            var corr = 0.0
            for (i in 0 until length - lag) {
                corr += (buffer[i] / 32768.0) * (buffer[i + lag] / 32768.0)
            }
            if (corr > maxCorr) {
                maxCorr = corr
                bestLag = lag
            }
        }
        return if (bestLag > 0) sampleRate.toDouble() / bestLag else -1.0
    }
}
""",
    "app/src/main/java/com/example/aimusicstudio/AiSongGenerator.kt": """package com.example.aimusicstudio

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
                prompt + ". JSON format: {\\"bpm\\": 124, \\"grid\\": [[16 ints], ... 8 arrays total]}. " +
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
""",
    "app/src/main/java/com/example/aimusicstudio/MainActivity.kt": """package com.example.aimusicstudio

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.*
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*

class MainActivity : AppCompatActivity() {
    private val synth = SynthEngine()
    private val autoTune = AutoTuneProcessor()
    private val uiScope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private val stepButtons = Array(SynthEngine.NUM_TRACKS) { arrayOfNulls<Button>(SynthEngine.NUM_STEPS) }
    private val numPianoRows = 24
    private val pianoRollButtons = Array(numPianoRows) { arrayOfNulls<Button>(SynthEngine.NUM_STEPS) }
    private val pianoKeyLabels = arrayOfNulls<TextView>(numPianoRows)
    private var currentPianoTrack = 5
    private var isPianoRollVisible = false

    private lateinit var viewFlipper: ViewFlipper
    private lateinit var btnToggleView: Button
    private lateinit var tvStatus: TextView
    private lateinit var tvAutoTuneNote: TextView

    private var selectedKey = 0
    private var selectedScale = "Minor"
    private var selectedStyle = "Trap / Hip-Hop"
    private val keyNames = arrayOf("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

    private val trackColors = intArrayOf(
        Color.parseColor("#FF5252"), Color.parseColor("#FF9800"),
        Color.parseColor("#FFEB3B"), Color.parseColor("#E040FB"),
        Color.parseColor("#448AFF"), Color.parseColor("#00E676"),
        Color.parseColor("#18FFFF"), Color.parseColor("#B388FF")
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val rootLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.parseColor("#121318"))
            setPadding(14, 10, 14, 8)
        }

        val topBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }

        val btnPlay = Button(this).apply {
            text = "▶ PLAY"
            setBackgroundColor(Color.parseColor("#00C853"))
            setTextColor(Color.WHITE)
            setOnClickListener {
                if (synth.isPlaying) {
                    synth.stop()
                    text = "▶ PLAY"
                    setBackgroundColor(Color.parseColor("#00C853"))
                } else {
                    synth.start()
                    text = "⏹ STOP"
                    setBackgroundColor(Color.parseColor("#D50000"))
                }
            }
        }
        topBar.addView(btnPlay)

        btnToggleView = Button(this).apply {
            text = "🎹 PIANO ROLL"
            setBackgroundColor(Color.parseColor("#00ACC1"))
            setTextColor(Color.WHITE)
            setOnClickListener {
                isPianoRollVisible = !isPianoRollVisible
                if (isPianoRollVisible) {
                    viewFlipper.displayedChild = 1
                    text = "🎛 8-TRACK GRID"
                    refreshPianoRollUI()
                } else {
                    viewFlipper.displayedChild = 0
                    text = "🎹 PIANO ROLL"
                    refreshGridUI()
                }
            }
        }
        topBar.addView(btnToggleView, LinearLayout.LayoutParams(-2, -2).apply { leftMargin = 10 })

        val btnAiCompose = Button(this).apply {
            text = "✨ AI SONG"
            setBackgroundColor(Color.parseColor("#6200EA"))
            setTextColor(Color.WHITE)
            setOnClickListener { showAiComposerDialog() }
        }
        topBar.addView(btnAiCompose, LinearLayout.LayoutParams(-2, -2).apply { leftMargin = 10 })

        val btnExport = Button(this).apply {
            text = "💾 WAV"
            setBackgroundColor(Color.parseColor("#2962FF"))
            setTextColor(Color.WHITE)
            setOnClickListener {
                tvStatus.text = "Rendering WAV..."
                uiScope.launch(Dispatchers.IO) {
                    val file = synth.exportWavFile(this@MainActivity, bars = 2)
                    withContext(Dispatchers.Main) {
                        tvStatus.text = "Saved: ${file.name}"
                        Toast.makeText(this@MainActivity, "Exported to ${file.absolutePath}", Toast.LENGTH_LONG).show()
                    }
                }
            }
        }
        topBar.addView(btnExport, LinearLayout.LayoutParams(-2, -2).apply { leftMargin = 10 })

        tvStatus = TextView(this).apply {
            text = "120 BPM | Ready"
            setTextColor(Color.parseColor("#B0BEC5"))
            textSize = 12f
            setPadding(16, 0, 0, 0)
        }
        topBar.addView(tvStatus)
        rootLayout.addView(topBar)

        val tuneBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Color.parseColor("#1E2029"))
            setPadding(10, 4, 10, 4)
        }

        val btnAutoTune = ToggleButton(this).apply {
            textOn = "🎙 AUTO-TUNE: ON"
            textOff = "🎙 AUTO-TUNE: OFF"
            text = textOff
            textSize = 11f
            setOnCheckedChangeListener { _, isChecked ->
                if (isChecked) startMicAutoTune(this) else autoTune.stop()
            }
        }
        tuneBar.addView(btnAutoTune)

        val spinnerKey = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, keyNames)
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(p0: AdapterView<*>?, p1: View?, pos: Int, p3: Long) {
                    selectedKey = pos
                    autoTune.rootKey = pos
                    refreshGridUI()
                }
                override fun onNothingSelected(p0: AdapterView<*>?) {}
            }
        }
        tuneBar.addView(spinnerKey)

        val scalesList = arrayOf("Minor", "Major", "Pentatonic", "Chromatic")
        val spinnerScale = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, scalesList)
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(p0: AdapterView<*>?, p1: View?, pos: Int, p3: Long) {
                    selectedScale = scalesList[pos]
                    autoTune.scaleType = selectedScale
                    refreshGridUI()
                }
                override fun onNothingSelected(p0: AdapterView<*>?) {}
            }
        }
        tuneBar.addView(spinnerScale)

        val seekRetune = SeekBar(this).apply {
            max = 100
            progress = 85
            layoutParams = LinearLayout.LayoutParams(150, -2)
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(s: SeekBar?, p: Int, b: Boolean) {
                    autoTune.retuneSpeed = (p / 100f).coerceAtLeast(0.05f)
                }
                override fun onStartTrackingTouch(s: SeekBar?) {}
                override fun onStopTrackingTouch(s: SeekBar?) {}
            })
        }
        tuneBar.addView(seekRetune)

        tvAutoTuneNote = TextView(this).apply {
            text = "🎤 --"
            setTextColor(Color.parseColor("#00E676"))
            typeface = Typeface.MONOSPACE
            textSize = 13f
            setPadding(12, 0, 0, 0)
        }
        tuneBar.addView(tvAutoTuneNote)
        rootLayout.addView(tuneBar, LinearLayout.LayoutParams(-1, -2).apply { topMargin = 6; bottomMargin = 6 })

        viewFlipper = ViewFlipper(this)
        viewFlipper.addView(buildSequencerView())
        viewFlipper.addView(buildPianoRollView())
        rootLayout.addView(viewFlipper, LinearLayout.LayoutParams(-1, 0, 1f))

        val padBar = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, 6, 0, 2)
        }
        for (t in 0 until SynthEngine.NUM_TRACKS) {
            val padBtn = Button(this).apply {
                text = "PAD\\n${SynthEngine.TRACK_NAMES[t]}"
                textSize = 9f
                setTextColor(Color.BLACK)
                typeface = Typeface.DEFAULT_BOLD
                setBackgroundColor(trackColors[t])
                layoutParams = LinearLayout.LayoutParams(0, 64, 1f).apply { setMargins(3, 0, 3, 0) }
                setOnClickListener {
                    val defaultMidi = if (t < 4) 36 else synth.getTrackBaseMidi(t) + selectedKey
                    synth.triggerNotePreview(t, defaultMidi)
                }
            }
            padBar.addView(padBtn)
        }
        rootLayout.addView(padBar, LinearLayout.LayoutParams(-1, -2))
        setContentView(rootLayout)

        AiSongGenerator.generateLocalAiSong(synth, selectedStyle, selectedKey, selectedScale)
        refreshGridUI()
        refreshPianoRollUI()

        synth.onStepChanged = { activeStep -> runOnUiThread { highlightPlayhead(activeStep) } }
        autoTune.onPitchDetected = { note, inHz, outHz ->
            runOnUiThread {
                tvAutoTuneNote.text = if (inHz > 0) "🎤 $note (${inHz}→${outHz}Hz)" else "🎤 --"
            }
        }
    }

    private fun buildSequencerView(): View {
        val scrollGrid = ScrollView(this)
        val hScrollGrid = HorizontalScrollView(this)
        val gridContainer = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        for (t in 0 until SynthEngine.NUM_TRACKS) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(0, 2, 0, 2)
            }
            val tvTrack = TextView(this).apply {
                text = if (t >= 4) "🎹 ${SynthEngine.TRACK_NAMES[t]}" else SynthEngine.TRACK_NAMES[t]
                setTextColor(trackColors[t])
                typeface = Typeface.DEFAULT_BOLD
                width = 175
                textSize = 12f
                setOnClickListener {
                    if (t >= 4) {
                        currentPianoTrack = t
                        isPianoRollVisible = true
                        viewFlipper.displayedChild = 1
                        btnToggleView.text = "🎛 8-TRACK GRID"
                        refreshPianoRollUI()
                    } else {
                        synth.trackMuted[t] = !synth.trackMuted[t]
                        alpha = if (synth.trackMuted[t]) 0.35f else 1.0f
                    }
                }
            }
            row.addView(tvTrack)

            for (s in 0 until SynthEngine.NUM_STEPS) {
                val btnStep = Button(this).apply {
                    layoutParams = LinearLayout.LayoutParams(76, 52).apply { setMargins(3, 2, 3, 2) }
                    setPadding(0, 0, 0, 0)
                    textSize = 10f
                    setTextColor(Color.BLACK)
                    setOnClickListener {
                        toggleStepNote(t, s)
                        refreshGridUI()
                    }
                }
                stepButtons[t][s] = btnStep
                row.addView(btnStep)
            }
            gridContainer.addView(row)
        }
        hScrollGrid.addView(gridContainer)
        scrollGrid.addView(hScrollGrid)
        return scrollGrid
    }

    private fun buildPianoRollView(): View {
        val container = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Color.parseColor("#181A22"))
            setPadding(10, 4, 10, 4)
        }
        val melodicTracks = arrayOf("Sub Bass (Track 5)", "Saw Lead (Track 6)", "FM Keys (Track 7)", "Warm Pad (Track 8)")
        val spTrackSelect = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, melodicTracks)
            setSelection(currentPianoTrack - 4)
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(p0: AdapterView<*>?, p1: View?, pos: Int, p3: Long) {
                    currentPianoTrack = pos + 4
                    refreshPianoRollUI()
                }
                override fun onNothingSelected(p0: AdapterView<*>?) {}
            }
        }
        header.addView(spTrackSelect)

        val btnClearTrack = Button(this).apply {
            text = "Clear Notes"
            textSize = 11f
            setBackgroundColor(Color.parseColor("#37474F"))
            setTextColor(Color.WHITE)
            setOnClickListener {
                synth.grid[currentPianoTrack].fill(0)
                refreshPianoRollUI()
                refreshGridUI()
            }
        }
        header.addView(btnClearTrack, LinearLayout.LayoutParams(-2, -2).apply { leftMargin = 16 })
        container.addView(header)

        val vScroll = ScrollView(this)
        val hScroll = HorizontalScrollView(this)
        val matrix = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        for (r in 0 until numPianoRows) {
            val semitoneOffset = (numPianoRows - 1) - r
            val rowLayout = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
            }
            val tvKey = TextView(this).apply {
                width = 120
                height = 46
                gravity = Gravity.CENTER_VERTICAL or Gravity.END
                setPadding(0, 0, 12, 0)
                textSize = 11f
                typeface = Typeface.MONOSPACE
                setOnClickListener {
                    val midi = synth.getTrackBaseMidi(currentPianoTrack) + semitoneOffset
                    synth.triggerNotePreview(currentPianoTrack, midi)
                }
            }
            pianoKeyLabels[r] = tvKey
            rowLayout.addView(tvKey)

            for (s in 0 until SynthEngine.NUM_STEPS) {
                val cellBtn = Button(this).apply {
                    layoutParams = LinearLayout.LayoutParams(76, 44).apply { setMargins(2, 1, 2, 1) }
                    setPadding(0, 0, 0, 0)
                    textSize = 9f
                    setTextColor(Color.BLACK)
                    setOnClickListener {
                        val targetMidi = synth.getTrackBaseMidi(currentPianoTrack) + semitoneOffset
                        if (synth.grid[currentPianoTrack][s] == targetMidi) {
                            synth.grid[currentPianoTrack][s] = 0
                        } else {
                            synth.grid[currentPianoTrack][s] = targetMidi
                            synth.triggerNotePreview(currentPianoTrack, targetMidi)
                        }
                        refreshPianoRollUI()
                        refreshGridUI()
                    }
                }
                pianoRollButtons[r][s] = cellBtn
                rowLayout.addView(cellBtn)
            }
            matrix.addView(rowLayout)
        }
        hScroll.addView(matrix)
        vScroll.addView(hScroll)
        container.addView(vScroll, LinearLayout.LayoutParams(-1, 0, 1f))
        return container
    }

    private fun toggleStepNote(track: Int, step: Int) {
        val current = synth.grid[track][step]
        if (track < 4) {
            synth.grid[track][step] = if (current == 0) 36 else 0
            if (synth.grid[track][step] > 0) synth.triggerNotePreview(track, 36)
        } else {
            val baseMidi = synth.getTrackBaseMidi(track)
            val nextMidi = when (current) {
                0 -> baseMidi + selectedKey
                baseMidi + selectedKey -> baseMidi + selectedKey + 3
                baseMidi + selectedKey + 3 -> baseMidi + selectedKey + 7
                else -> 0
            }
            synth.grid[track][step] = nextMidi
            if (nextMidi > 0) synth.triggerNotePreview(track, nextMidi)
        }
    }

    private fun refreshGridUI() {
        tvStatus.text = "${synth.bpm} BPM | Key: ${keyNames[selectedKey]} $selectedScale"
        for (t in 0 until SynthEngine.NUM_TRACKS) {
            for (s in 0 until SynthEngine.NUM_STEPS) {
                val btn = stepButtons[t][s] ?: continue
                val valNote = synth.grid[t][s]
                if (valNote > 0) {
                    btn.setBackgroundColor(trackColors[t])
                    val octave = (valNote / 12) - 1
                    btn.text = if (t < 4) "●" else "${keyNames[valNote % 12]}$octave"
                } else {
                    val beatGroupColor = if ((s / 4) % 2 == 0) "#262936" else "#1D1F2A"
                    btn.setBackgroundColor(Color.parseColor(beatGroupColor))
                    btn.text = ""
                }
            }
        }
    }

    private fun refreshPianoRollUI() {
        val baseMidi = synth.getTrackBaseMidi(currentPianoTrack)
        val activeColor = trackColors[currentPianoTrack]
        val blackKeyIndices = setOf(1, 3, 6, 8, 10)

        for (r in 0 until numPianoRows) {
            val semitoneOffset = (numPianoRows - 1) - r
            val rowMidi = baseMidi + semitoneOffset
            val noteIdx = rowMidi % 12
            val octave = (rowMidi / 12) - 1
            val isBlackKey = blackKeyIndices.contains(noteIdx)

            pianoKeyLabels[r]?.apply {
                text = "${keyNames[noteIdx]}$octave"
                setBackgroundColor(if (isBlackKey) Color.parseColor("#161820") else Color.parseColor("#CFD8DC"))
                setTextColor(if (isBlackKey) Color.WHITE else Color.BLACK)
            }

            for (s in 0 until SynthEngine.NUM_STEPS) {
                val btn = pianoRollButtons[r][s] ?: continue
                if (synth.grid[currentPianoTrack][s] == rowMidi) {
                    btn.setBackgroundColor(activeColor)
                    btn.text = keyNames[noteIdx]
                } else {
                    val bg = when {
                        isBlackKey -> "#181A24"
                        (s / 4) % 2 == 0 -> "#252836"
                        else -> "#1F222E"
                    }
                    btn.setBackgroundColor(Color.parseColor(bg))
                    btn.text = ""
                }
            }
        }
    }

    private fun highlightPlayhead(activeStep: Int) {
        if (!isPianoRollVisible) {
            for (t in 0 until SynthEngine.NUM_TRACKS) {
                for (s in 0 until SynthEngine.NUM_STEPS) {
                    stepButtons[t][s]?.alpha = if (s == activeStep) 0.55f else 1.0f
                }
            }
        } else {
            for (r in 0 until numPianoRows) {
                for (s in 0 until SynthEngine.NUM_STEPS) {
                    pianoRollButtons[r][s]?.alpha = if (s == activeStep) 0.55f else 1.0f
                }
            }
        }
    }

    private fun showAiComposerDialog() {
        val dialogLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(40, 24, 40, 16)
        }
        val styles = arrayOf("Trap / Hip-Hop", "House / Techno", "Synthwave / Pop")
        val spStyle = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, styles)
        }
        dialogLayout.addView(spStyle)
        val etPrompt = EditText(this).apply { hint = "Custom prompt (optional)" }
        dialogLayout.addView(etPrompt)
        val etApiKey = EditText(this).apply { hint = "Gemini API Key (leave blank for built-in AI)" }
        dialogLayout.addView(etApiKey)

        AlertDialog.Builder(this)
            .setTitle("✨ AI Song Assistant")
            .setView(dialogLayout)
            .setPositiveButton("Generate") { _, _ ->
                selectedStyle = styles[spStyle.selectedItemPosition]
                val apiKey = etApiKey.text.toString().trim()
                val prompt = etPrompt.text.toString().trim().ifEmpty { selectedStyle }
                if (apiKey.isNotEmpty()) {
                    uiScope.launch(Dispatchers.IO) {
                        val ok = AiSongGenerator.generateCloudGeminiPattern(apiKey, prompt, synth)
                        if (!ok) AiSongGenerator.generateLocalAiSong(synth, selectedStyle, selectedKey, selectedScale)
                        withContext(Dispatchers.Main) { refreshGridUI(); refreshPianoRollUI() }
                    }
                } else {
                    AiSongGenerator.generateLocalAiSong(synth, selectedStyle, selectedKey, selectedScale)
                    refreshGridUI()
                    refreshPianoRollUI()
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun startMicAutoTune(toggleBtn: ToggleButton) {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            toggleBtn.isChecked = false
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 101)
            return
        }
        autoTune.start()
    }

    override fun onDestroy() {
        super.onDestroy()
        synth.stop()
        autoTune.stop()
        uiScope.cancel()
    }
}
"""
}

base_dir = "AIMusicStudioProject"
for rel_path, content in PROJECT_FILES.items():
    full_path = os.path.join(base_dir, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
print("Project files written successfully!")
