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
mcp = fastmcp.FastMCP("Music MCP Server")
pa = pyaudio.PyAudio()
stream = None
thread = None
recording = False
table = None

def start():
    global stream, table
    stream = pa.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=RATE,
                    input=True,
                    frames_per_buffer=CHUNK)
    table = yaml.load(open(TABLE), yaml.Loader) or {}   

def stop():
    stream.stop_stream()
    stream.close()
    pa.terminate()

def writeTable(id, val):
    if val == None:
        del table[id]
    else:
        table[id] = val
    yaml.dump(table, open(TABLE, "w"))

def record():
    frames = []
    while recording:
        data = stream.read(CHUNK)
        frames.append(data)
    wf = wave.open(CURR, "wb")
    wf.setnchannels(1)
    wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
    wf.setframerate(RATE)
    wf.writeframes(b"".join(frames))
    wf.close()
    writeTable("curr", {"size" : path.getsize(CURR), "time" : len(frames) * CHUNK/RATE})

@mcp.tool
def startRecording() -> bool:
    """Start recording"""
    global thread, recording
    if recording:
        return False
    thread = threading.Thread(target=record)
    recording = True
    thread.start()
    return True
    
@mcp.tool
def stopRecording() -> bool:
    """Stop recording and save the audio to curr.wav"""
    global recording
    if not recording:
        return False
    recording = False
    thread.join()
    return True

@mcp.tool
def saveCurr(name : str) -> bool:
    """Save a copy of curr.wav to the given name, which must not already exist"""
    if "curr" not in table or name in table:
        return False
    shutil.copy(CURR, path.join(SAVED, name + ".wav"))
    writeTable(name, dict(table["curr"]))
    return True
    
@mcp.tool
def setAsCurr(name : str) -> bool:
    """Copy the saved file with the given name to curr.wav"""
    if name not in table:
        return False
    shutil.copy(path.join(SAVED, name + ".wav"), CURR)
    writeTable("curr", dict(table[name]))
    return True

@mcp.tool
def delete(name : str) -> bool:
    """Delete the saved file with the given name"""
    if name == "curr" or name not in table:
        return False
    os.remove(path.join(SAVED, name + ".wav"))
    writeTable(name, None)
    return True

@mcp.resource("data://recordings")
def recordings() -> object:
    """Returns a dict mapping a saved filename or "curr" to an object with a "size" attribute (the file size in bytes) and a "time" attribute (the runtime in seconds)"""
    return table

@mcp.resource("data://curr")
def curr() -> str:
    """Returns the full file path of curr.wav"""
    return CURR

if __name__ == "main":
    start()
    mcp.run()
    stop()