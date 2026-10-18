import asyncio
from io import BytesIO
import os
import traceback
import uuid
import edge_tts
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader
from sqlalchemy.orm import Session

from ai_service import generate_podcast_script
from database import engine, get_db
from models import Base, Episode

# Ensure database schema exists
Base.metadata.create_all(bind=engine)

# Absolute path resolution
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
AUDIO_DIR = os.path.join(STATIC_DIR, "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)
MAX_UPLOAD_SIZE = 10 * 1024 * 1024
MAX_SOURCE_CHARACTERS = 20000

app = FastAPI(title="DevCast AI Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/audio", StaticFiles(directory=AUDIO_DIR), name="audio")


@app.get("/episodes")
def get_episodes(db: Session = Depends(get_db)):
  try:
    return db.query(Episode).order_by(Episode.id.desc()).all()
  except Exception as e:
    print(f"[Error fetching episodes]: {e}")
    return []


@app.post("/upload-code")
async def upload_code(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
  try:
    contents = await file.read(MAX_UPLOAD_SIZE + 1)
  except Exception as e:
    raise HTTPException(status_code=400, detail=f"Failed to read file: {str(e)}")

  if len(contents) > MAX_UPLOAD_SIZE:
    raise HTTPException(status_code=413, detail="Files must be 10 MB or smaller.")
  if not contents:
    raise HTTPException(status_code=400, detail="Uploaded file is empty.")

  filename = file.filename or "uploaded-file"
  pdf_data = None
  if (
      os.path.splitext(filename)[1].lower() == ".pdf"
      or b"%PDF-" in contents[:1024]
  ):
    try:
      reader = PdfReader(BytesIO(contents))
      if reader.is_encrypted:
        raise HTTPException(
            status_code=400,
            detail="This PDF is password-protected. Upload an unlocked PDF.",
        )
      source_text = "\n".join(
          page.extract_text() or "" for page in reader.pages
      )
      if not source_text.strip():
        pdf_data = contents
        source_text = "This PDF contains no selectable text. Analyze the attached PDF pages."
    except HTTPException:
      raise
    except Exception as e:
      raise HTTPException(
          status_code=400, detail=f"Could not read this PDF: {str(e)}"
      )
    if not source_text.strip():
      raise HTTPException(
          status_code=400,
          detail="No selectable text was found in this PDF. Scanned PDFs need OCR before upload.",
      )
  else:
    try:
      source_text = contents.decode("utf-8-sig")
    except UnicodeDecodeError:
      raise HTTPException(
          status_code=400,
          detail="This file is not readable text. Upload a PDF or a text-based document or code file.",
      )
    if "\x00" in source_text:
      raise HTTPException(
          status_code=400,
          detail="This file appears to be binary. Upload a PDF or a text-based document or code file.",
      )

  source_text = source_text.strip()
  if not source_text:
    raise HTTPException(status_code=400, detail="The uploaded file has no text.")
  source_text = source_text[:MAX_SOURCE_CHARACTERS]

  # 1. Script synthesis with Gemini
  try:
    script = generate_podcast_script(filename, source_text, pdf_data=pdf_data)
    if not script or not script.strip():
      raise ValueError("Gemini returned an empty script.")
  except Exception as e:
    print(f"[Gemini Error]: {traceback.format_exc()}")
    raise HTTPException(
        status_code=500, detail=f"AI Script Generation Error: {str(e)}"
    )

  # 2. Audio synthesis with Edge-TTS
  try:
    audio_filename = f"{uuid.uuid4().hex}.mp3"
    audio_filepath = os.path.join(AUDIO_DIR, audio_filename)
    communicate = edge_tts.Communicate(
        text=script, voice="en-US-GuyNeural", rate="+15%"
    )
    await communicate.save(audio_filepath)
  except Exception as e:
    print(f"[Edge-TTS Error]: {traceback.format_exc()}")
    raise HTTPException(
        status_code=500, detail=f"Audio Synthesis Error: {str(e)}"
    )

  # 3. Store episode in Database
  try:
    audio_url = f"/audio/{audio_filename}"
    episode = Episode(
        filename=filename,
        summary=script,
        audio_path=audio_url,
    )
    db.add(episode)
    db.commit()
    db.refresh(episode)
  except Exception as e:
    db.rollback()
    print(f"[Database Error]: {traceback.format_exc()}")
    raise HTTPException(
        status_code=500, detail=f"Database Save Error: {str(e)}"
    )

  return {
      "status": "success",
      "episode_id": episode.id,
      "filename": episode.filename,
      "script": episode.summary,
      "audio_url": audio_url,
  }


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
  return """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>DevCast AI Studio</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          fontFamily: {
            sans: ['"Plus Jakarta Sans"', 'sans-serif'],
            mono: ['"JetBrains Mono"', 'monospace'],
          },
          colors: {
            studio: {
              950: '#06080F',
              900: '#0B0F19',
              850: '#111726',
              800: '#161F33',
              700: '#1F2C47',
              accent: '#6366F1',
              accentHover: '#4F46E5',
              glow: '#818CF8'
            }
          }
        }
      }
    }
  </script>
  <style>
    body {
      background-color: #06080F;
      background-image: 
        radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.12) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(14, 165, 233, 0.08) 0px, transparent 50%);
    }
    .glass-panel {
      background: rgba(17, 23, 38, 0.7);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.07);
    }
    .custom-scroll::-webkit-scrollbar {
      width: 5px;
    }
    .custom-scroll::-webkit-scrollbar-track {
      background: transparent;
    }
    .custom-scroll::-webkit-scrollbar-thumb {
      background: rgba(255, 255, 255, 0.1);
      border-radius: 9999px;
    }
    .custom-scroll::-webkit-scrollbar-thumb:hover {
      background: rgba(255, 255, 255, 0.2);
    }
  </style>
</head>
<body class="text-slate-100 font-sans min-h-screen flex flex-col antialiased selection:bg-indigo-500 selection:text-white">

  <!-- Top Navigation Header -->
  <header class="border-b border-white/5 bg-studio-950/60 backdrop-blur-md sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <div class="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 to-cyan-400 p-[1px] shadow-lg shadow-indigo-500/20">
          <div class="w-full h-full bg-studio-950 rounded-[11px] flex items-center justify-center">
            <svg class="w-5 h-5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z" />
            </svg>
          </div>
        </div>
        <div>
          <span class="font-extrabold text-white tracking-tight text-lg">DevCast<span class="text-indigo-400">.ai</span></span>
          <span class="text-[10px] tracking-wider uppercase font-mono px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 ml-2">Studio</span>
        </div>
      </div>
      <div class="flex items-center gap-4 text-xs font-mono text-slate-400">
        <span class="flex items-center gap-1.5">
          <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span> Gemini 3.8 Active
        </span>
      </div>
    </div>
  </header>

  <!-- Main Content Layout -->
  <main class="flex-1 max-w-7xl w-full mx-auto px-6 py-8 grid grid-cols-1 lg:grid-cols-12 gap-8">
    
    <!-- Left Column: Synthesizer & Active Player (7 cols) -->
    <div class="lg:col-span-7 space-y-6">
      
      <!-- Studio Upload Dropzone -->
      <section class="glass-panel rounded-2xl p-6 relative overflow-hidden shadow-2xl">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-base font-bold text-white tracking-wide">Turn a File into a Podcast</h2>
            <p class="text-xs text-slate-400 mt-0.5">Upload a PDF, document, or code file and get an AI-narrated MP3.</p>
          </div>
          <span class="text-[11px] font-mono text-slate-400 bg-white/5 border border-white/5 px-2.5 py-1 rounded-md">PDF · text · code</span>
        </div>

        <form id="uploadForm" class="space-y-4">
          <div 
            id="dropArea" 
            class="border-2 border-dashed border-slate-700 hover:border-indigo-500/60 transition-all rounded-xl p-8 flex flex-col items-center justify-center text-center cursor-pointer bg-studio-900/40 hover:bg-studio-800/40 group"
          >
            <input type="file" id="fileInput" accept="*/*" class="hidden" />
            
            <div class="w-12 h-12 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 group-hover:scale-110 transition-transform mb-3">
              <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
            </div>
            
            <p class="text-sm font-semibold text-slate-200" id="fileLabel">Choose a file or drop it here</p>
            <p class="text-xs text-slate-500 mt-1" id="fileDetails">PDF, text, or code files · 10 MB max</p>
            <p class="text-[11px] text-slate-500 mt-2">Only the selected file is uploaded; its contents are sent to AI to create the narration.</p>
          </div>

          <div class="flex items-center justify-between pt-2">
            <span id="selectedFileName" class="text-xs font-mono text-indigo-300 truncate max-w-[280px]"></span>
            <button 
              type="submit" 
              id="generateBtn" 
              disabled
              class="px-6 py-2.5 rounded-xl font-semibold text-xs tracking-wide text-white bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 disabled:cursor-not-allowed transition-all shadow-lg shadow-indigo-600/25 flex items-center gap-2 ml-auto"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              </svg>
              <span>Generate Audio</span>
            </button>
          </div>
        </form>

        <!-- Live Step Timeline Indicator -->
        <div id="statusContainer" class="hidden mt-5 pt-4 border-t border-white/5 space-y-3">
          <div class="flex items-center justify-between text-xs">
            <span id="statusMessage" class="text-slate-300 font-medium">Initializing pipeline...</span>
            <span id="statusPercent" class="font-mono text-indigo-400">0%</span>
          </div>
          <div class="w-full bg-studio-900 rounded-full h-1.5 overflow-hidden">
            <div id="progressBar" class="bg-gradient-to-r from-indigo-500 to-cyan-400 h-1.5 rounded-full transition-all duration-300 w-0"></div>
          </div>
        </div>
      </section>

      <!-- Custom Acoustic Player Card -->
      <section id="playerCard" class="hidden glass-panel rounded-2xl p-6 shadow-2xl space-y-5 border-indigo-500/30">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-indigo-800 flex items-center justify-center shadow-lg shadow-indigo-600/30">
              <svg class="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
              </svg>
            </div>
            <div>
              <span class="text-[10px] font-mono uppercase tracking-widest text-indigo-400 font-bold block" id="currentEpisodeBadge">Episode #</span>
              <h3 class="text-base font-bold text-white tracking-wide truncate max-w-sm" id="currentTrackTitle">Filename.py</h3>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <div class="flex items-center gap-2">
              <a id="downloadAudio" class="text-xs font-mono px-2.5 py-1 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/20 transition" download>Download MP3</a>
              <button id="speedBtn" class="text-xs font-mono px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-slate-300 border border-white/5 transition">1.0x</button>
            </div>
          </div>
        </div>

        <audio id="audioElement" preload="metadata" class="hidden"></audio>

        <!-- Player Progress -->
        <div class="space-y-2">
          <div id="timelineContainer" class="w-full bg-studio-900 rounded-full h-2 cursor-pointer relative group">
            <div id="playProgress" class="bg-gradient-to-r from-indigo-500 to-cyan-400 h-2 rounded-full w-0 relative">
              <span class="w-3 h-3 bg-white rounded-full absolute -right-1.5 -top-0.5 shadow-md scale-0 group-hover:scale-100 transition-transform"></span>
            </div>
          </div>
          <div class="flex justify-between text-[11px] font-mono text-slate-400">
            <span id="currentTime">0:00</span>
            <span id="durationTime">0:00</span>
          </div>
        </div>

        <!-- Controls -->
        <div class="flex items-center justify-center gap-6">
          <button id="backwardBtn" class="text-slate-400 hover:text-white transition p-2">
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12.066 11.2a1 1 0 000 1.6l5.334 4A1 1 0 0019 16V8a1 1 0 00-1.6-.8l-5.334 4zM4.066 11.2a1 1 0 000 1.6l5.334 4A1 1 0 0011 16V8a1 1 0 00-1.6-.8l-5.334 4z" />
            </svg>
          </button>
          <button id="masterPlayBtn" class="w-12 h-12 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white flex items-center justify-center shadow-xl shadow-indigo-600/40 hover:scale-105 transition-all">
            <svg id="playIcon" class="w-6 h-6 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z"/>
            </svg>
            <svg id="pauseIcon" class="w-6 h-6 hidden" fill="currentColor" viewBox="0 0 24 24">
              <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
            </svg>
          </button>
          <button id="forwardBtn" class="text-slate-400 hover:text-white transition p-2">
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11.933 12.8a1 1 0 000-1.6L6.6 7.2A1 1 0 005 8v8a1 1 0 001.6.8l5.333-4zM19.933 12.8a1 1 0 000-1.6l-5.333-4A1 1 0 0013 8v8a1 1 0 001.6.8l5.333-4z" />
            </svg>
          </button>
        </div>

        <!-- Script Display Accordion -->
        <div class="border-t border-white/5 pt-4">
          <label class="text-[11px] font-mono tracking-wider text-slate-400 uppercase font-semibold block mb-2">Narrative Transcript</label>
          <div class="bg-studio-950/70 border border-white/5 rounded-xl p-4 max-h-48 overflow-y-auto custom-scroll">
            <p id="transcriptText" class="text-xs text-slate-300 leading-relaxed font-sans whitespace-pre-wrap"></p>
          </div>
        </div>
      </section>

    </div>

    <!-- Right Column: Episode Archive (5 cols) -->
    <div class="lg:col-span-5">
      <section class="glass-panel rounded-2xl p-6 shadow-2xl h-full flex flex-col">
        <div class="flex items-center justify-between pb-4 border-b border-white/5">
          <div class="flex items-center gap-2">
            <h2 class="text-base font-bold text-white tracking-wide">Episode Archive</h2>
            <span id="archiveCount" class="text-[11px] font-mono bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 px-2 py-0.5 rounded-full">0</span>
          </div>
          <button id="refreshBtn" class="text-xs text-slate-400 hover:text-white transition flex items-center gap-1 font-mono">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Sync
          </button>
        </div>

        <div id="episodesList" class="flex-1 overflow-y-auto custom-scroll space-y-3 pt-4 pr-1 max-h-[580px]">
          <!-- Populated dynamically via JS -->
        </div>
      </section>
    </div>

  </main>

  <script>
    const dropArea = document.getElementById('dropArea');
    const fileInput = document.getElementById('fileInput');
    const fileLabel = document.getElementById('fileLabel');
    const fileDetails = document.getElementById('fileDetails');
    const selectedFileName = document.getElementById('selectedFileName');
    const generateBtn = document.getElementById('generateBtn');
    const uploadForm = document.getElementById('uploadForm');

    const statusContainer = document.getElementById('statusContainer');
    const statusMessage = document.getElementById('statusMessage');
    const statusPercent = document.getElementById('statusPercent');
    const progressBar = document.getElementById('progressBar');

    const playerCard = document.getElementById('playerCard');
    const audioElement = document.getElementById('audioElement');
    const downloadAudio = document.getElementById('downloadAudio');
    const currentTrackTitle = document.getElementById('currentTrackTitle');
    const currentEpisodeBadge = document.getElementById('currentEpisodeBadge');
    const transcriptText = document.getElementById('transcriptText');
    const masterPlayBtn = document.getElementById('masterPlayBtn');
    const playIcon = document.getElementById('playIcon');
    const pauseIcon = document.getElementById('pauseIcon');
    const playProgress = document.getElementById('playProgress');
    const timelineContainer = document.getElementById('timelineContainer');
    const currentTimeDisplay = document.getElementById('currentTime');
    const durationTimeDisplay = document.getElementById('durationTime');
    const speedBtn = document.getElementById('speedBtn');
    const backwardBtn = document.getElementById('backwardBtn');
    const forwardBtn = document.getElementById('forwardBtn');

    const episodesList = document.getElementById('episodesList');
    const archiveCount = document.getElementById('archiveCount');
    const refreshBtn = document.getElementById('refreshBtn');

    let currentFile = null;

    // Dropzone logic
    dropArea.addEventListener('click', () => fileInput.click());
    dropArea.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropArea.classList.add('border-indigo-500', 'bg-studio-800/60');
    });
    ['dragleave', 'drop'].forEach(ev => {
      dropArea.addEventListener(ev, () => {
        dropArea.classList.remove('border-indigo-500', 'bg-studio-800/60');
      });
    });
    dropArea.addEventListener('drop', (e) => {
      e.preventDefault();
      if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length) handleFile(fileInput.files[0]);
    });

    function handleFile(file) {
      if (file.size > 10 * 1024 * 1024) {
        currentFile = null;
        fileInput.value = '';
        fileLabel.textContent = 'Choose a file or drop it here';
        fileDetails.textContent = 'Files must be 10 MB or smaller';
        selectedFileName.textContent = '';
        generateBtn.disabled = true;
        statusContainer.classList.remove('hidden');
        setStatus('This file is too large. Choose a file under 10 MB.', 0);
        return;
      }
      currentFile = file;
      statusContainer.classList.add('hidden');
      fileLabel.textContent = file.name;
      fileDetails.textContent = `${(file.size / 1024).toFixed(1)} KB · Ready to create your podcast`;
      selectedFileName.textContent = file.name;
      generateBtn.disabled = false;
    }

    // Pipeline submission
    uploadForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!currentFile) return;

      const formData = new FormData();
      formData.append('file', currentFile);

      generateBtn.disabled = true;
      statusContainer.classList.remove('hidden');
      setStatus('Step 1/2: Generating podcast script with Gemini...', 30);

      const timer = setTimeout(() => {
        setStatus('Step 2/2: Synthesizing neural audio with Edge-TTS...', 75);
      }, 2400);

      try {
        const response = await fetch('/upload-code', { method: 'POST', body: formData });
        clearTimeout(timer);
        const data = await response.json();

        if (!response.ok) throw new Error(data.detail || `Server error: ${response.status}`);

        setStatus('Complete!', 100);
        setTimeout(() => statusContainer.classList.add('hidden'), 1500);

        loadEpisodeIntoPlayer(data.filename, data.script, data.audio_url, data.episode_id);
        fetchEpisodes();
      } catch (err) {
        clearTimeout(timer);
        statusMessage.textContent = `Error: ${err.message}`;
        statusPercent.textContent = 'Failed';
        progressBar.classList.remove('from-indigo-500', 'to-cyan-400');
        progressBar.classList.add('bg-rose-500');
      } finally {
        generateBtn.disabled = false;
      }
    });

    function setStatus(msg, percent) {
      statusMessage.textContent = msg;
      statusPercent.textContent = `${percent}%`;
      progressBar.style.width = `${percent}%`;
      progressBar.classList.remove('bg-rose-500');
      progressBar.classList.add('bg-gradient-to-r', 'from-indigo-500', 'to-cyan-400');
    }

    // Audio Player Implementation
    function loadEpisodeIntoPlayer(filename, script, audioUrl, id) {
      playerCard.classList.remove('hidden');
      currentTrackTitle.textContent = filename;
      currentEpisodeBadge.textContent = `Episode #${id}`;
      transcriptText.textContent = script;
      audioElement.src = audioUrl;
      downloadAudio.href = audioUrl;
      downloadAudio.download = `${filename.replace(/\\.[^.]+$/, '') || 'podcast'}.mp3`;
      audioElement.play().then(() => updatePlayState(true)).catch(() => updatePlayState(false));
      playerCard.scrollIntoView({ behavior: 'smooth' });
    }

    masterPlayBtn.addEventListener('click', () => {
      if (audioElement.paused) {
          audioElement.play().then(() => updatePlayState(true)).catch(() => updatePlayState(false));
      } else {
        audioElement.pause();
        updatePlayState(false);
      }
    });

    function updatePlayState(isPlaying) {
      if (isPlaying) {
        playIcon.classList.add('hidden');
        pauseIcon.classList.remove('hidden');
      } else {
        playIcon.classList.remove('hidden');
        pauseIcon.classList.add('hidden');
      }
    }

    audioElement.addEventListener('timeupdate', () => {
      const current = audioElement.currentTime;
      const total = audioElement.duration || 1;
      playProgress.style.width = `${(current / total) * 100}%`;
      currentTimeDisplay.textContent = formatTime(current);
    });

    audioElement.addEventListener('loadedmetadata', () => {
      durationTimeDisplay.textContent = formatTime(audioElement.duration);
    });

    audioElement.addEventListener('ended', () => updatePlayState(false));

    timelineContainer.addEventListener('click', (e) => {
      const rect = timelineContainer.getBoundingClientRect();
      const pos = (e.clientX - rect.left) / rect.width;
      audioElement.currentTime = pos * audioElement.duration;
    });

    backwardBtn.addEventListener('click', () => audioElement.currentTime = Math.max(0, audioElement.currentTime - 5));
    forwardBtn.addEventListener('click', () => audioElement.currentTime = Math.min(audioElement.duration, audioElement.currentTime + 5));

    const speeds = [1.0, 1.25, 1.5, 2.0];
    let speedIndex = 0;
    speedBtn.addEventListener('click', () => {
      speedIndex = (speedIndex + 1) % speeds.length;
      const rate = speeds[speedIndex];
      audioElement.playbackRate = rate;
      speedBtn.textContent = `${rate.toFixed(2)}x`;
    });

    function formatTime(secs) {
      if (isNaN(secs)) return '0:00';
      const m = Math.floor(secs / 60);
      const s = Math.floor(secs % 60);
      return `${m}:${s < 10 ? '0' : ''}${s}`;
    }

    // Archive Loader
    async function fetchEpisodes() {
      try {
        const res = await fetch('/episodes');
        if (!res.ok) return;
        const episodes = await res.json();
        renderArchive(episodes);
      } catch (err) {
        console.error(err);
      }
    }

    function renderArchive(list) {
      archiveCount.textContent = list.length;
      if (!list || list.length === 0) {
        episodesList.innerHTML = `
          <div class="h-48 flex flex-col items-center justify-center text-center text-slate-500 space-y-2">
            <svg class="w-8 h-8 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            <p class="text-xs">No episodes compiled yet.</p>
          </div>
        `;
        return;
      }

      episodesList.replaceChildren();
      list.forEach((item) => {
        const episode = document.createElement('div');
        episode.className = 'glass-panel p-3.5 rounded-xl flex items-center justify-between gap-3 hover:border-indigo-500/30 transition group';

        const details = document.createElement('div');
        details.className = 'min-w-0';
        const heading = document.createElement('div');
        heading.className = 'flex items-center gap-2';
        const number = document.createElement('span');
        number.className = 'text-[10px] font-mono text-indigo-400 font-semibold';
        number.textContent = `#${item.id}`;
        const filename = document.createElement('h4');
        filename.className = 'text-xs font-semibold text-white truncate max-w-[180px]';
        filename.textContent = item.filename;
        heading.append(number, filename);

        const summary = document.createElement('p');
        summary.className = 'text-[11px] text-slate-400 truncate max-w-[210px] mt-0.5';
        summary.textContent = item.summary || '';
        details.append(heading, summary);

        const playButton = document.createElement('button');
        playButton.className = 'px-2.5 py-1.5 rounded-lg bg-indigo-600/10 hover:bg-indigo-600 text-indigo-400 hover:text-white text-xs font-mono transition flex items-center gap-1 flex-shrink-0';
        playButton.textContent = 'Play';
        playButton.addEventListener('click', () => {
          loadEpisodeIntoPlayer(item.filename, item.summary || '', item.audio_path, item.id);
        });

        episode.append(details, playButton);
        episodesList.append(episode);
      });
    }

    refreshBtn.addEventListener('click', fetchEpisodes);
    fetchEpisodes();
  </script>
</body>
</html>"""