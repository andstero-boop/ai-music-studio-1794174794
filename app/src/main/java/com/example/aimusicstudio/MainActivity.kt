package com.example.aimusicstudio

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
                text = "PAD\n${SynthEngine.TRACK_NAMES[t]}"
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
