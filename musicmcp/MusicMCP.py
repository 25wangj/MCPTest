import os.path as path
import os
import shutil
import pyaudio
import threading
import wave
import yaml
import fastmcp

CHUNK = 1024
RATE = 44100
PATH = path.dirname(path.abspath(__file__))
SAVED = path.join(PATH, "recordings")
CURR = path.join(PATH, "curr.wav")
TABLE = path.join(SAVED, "table.yaml")
mcp = fastmcp.FastMCP("MusicMCP")
pa = pyaudio.PyAudio()
recordStream = None
playStream = None
recordThread = None
playThread = None
recording = False
playing = False
lock = threading.Lock()
table = None

def start():
    global recordStream, playStream, table
    recordStream = pa.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)
    playStream = pa.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=RATE,
                    output=True,
                    frames_per_buffer=CHUNK)
    table = yaml.load(open(TABLE), yaml.Loader) or {}   

def stop():
    recordStream.stop_stream()
    recordStream.close()
    playStream.stop_stream()
    playStream.close()
    pa.terminate()

def fileData(file):
    wr = wave.open(file, "wr")  
    time = wr.getnframes() / wr.getframerate()
    wr.close()
    return {"size" : path.getsize(CURR), "time" : time}

def writeTable(id, val):
    if val == None:
        if id == "curr":
            wf = wave.open(CURR, "rb")   
            table[id] = {"size" : path.getsize(CURR), "time" : wf.getnframes() / wf.getframerate()};   
            wf.close()
        else:
            del table[id]
    else:
        table[id] = val
    yaml.dump(table, open(TABLE, "w"))

def record():
    frames = []
    while recording:
        data = recordStream.read(CHUNK)
        frames.append(data)
    with lock:
        wf = wave.open(CURR, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
        wf.setframerate(RATE)
        wf.writeframes(b"".join(frames))
        wf.close()
        writeTable("curr", None)

def play():
    with lock:
        wf = wave.open(CURR, "rb")
        data = wf.readframes(CHUNK)
        while data and playing:
            playStream.write(data)
            data = wf.readframes(CHUNK)
        wf.close()

@mcp.tool
def startRecording() -> bool:
    """Start recording.
    Returns True if successful, False otherwise"""
    global recordThread, recording
    if recording:
        return False
    recordThread = threading.Thread(target=record)
    recording = True
    recordThread.start()
    return True
    
@mcp.tool
def stopRecording() -> bool:
    """Stop recording and save the audio to curr.wav. May not be playing curr.wav at the same time.
    Returns True if successful, False otherwise."""
    global recording
    if not recording:
        return False
    recording = False
    recordThread.join()
    return True

@mcp.tool
def startPlaying() -> bool:
    """Start playing curr.wav.
    Returns True if successful, False otherwise"""
    global playThread, playing
    if playing:
        return False
    playThread = threading.Thread(target=play)
    playing = True
    playThread.start()
    return True

@mcp.tool
def stopPlaying() -> bool:
    """Stop playing curr.wav.
    Returns True if successful, False otherwise."""
    global playing
    if not playing:
        return False
    playing = False
    playThread.join()
    return True

@mcp.tool
def saveCurr(name : str) -> bool:
    """Save a copy of curr.wav to the given name, which must not already exist.
    Returns True if successful, False otherwise"""
    if "curr" not in table or name in table:
        return False
    shutil.copy(CURR, path.join(SAVED, name + ".wav"))
    writeTable(name, dict(table["curr"]))
    return True
    
@mcp.tool
def setAsCurr(name : str) -> bool:
    """If a full file path with a .wav extension is provided, the file is copied to curr.wav.
    If a file name is provided, the saved file with the given name is copied to curr.wav.
    Returns True if successful, False otherwise"""
    if path.isfile(name) and path.splitext(name)[1] == ".wav":
        shutil.copy(name, CURR)
        writeTable("curr", None)
    else: 
        if name not in table:
            return False
        shutil.copy(path.join(SAVED, name + ".wav"), CURR)
        writeTable("curr", dict(table[name]))
    return True

@mcp.tool
def delete(name : str) -> bool:
    """Delete the saved file with the given name.
    Returns True if successful, False otherwise."""
    if name == "curr" or name not in table:
        return False
    os.remove(path.join(SAVED, name + ".wav"))
    writeTable(name, None)
    return True

@mcp.resource("data://recordings")
def recordings() -> object:
    """Returns a dict mapping a saved filename or "curr" to an object with a "size" attribute (the file size in bytes) and a "time" attribute (the runtime in seconds)."""
    return table

@mcp.resource("data://curr")
def curr() -> str:
    """Returns the full file path of curr.wav."""
    return CURR

if __name__ == "__main__":
    start()
    mcp.run(transport="http", host="127.0.0.1", port=8000)
    stop()