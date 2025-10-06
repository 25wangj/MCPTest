import MusicServer

MusicServer.start()
while True:
    move = input("r to record, s to save, c to set as curr, d to delete, p to print, f to finish\n")
    if move == "r":
        input("Enter to start recording\n")
        MusicServer.startRecording()
        input("Enter to stop recording\n")
        MusicServer.stopRecording()
        print("Done")
    elif move == "s":
        name = input("Enter the filename\n")
        if MusicServer.saveCurr(name):
            print("Done")
        else:
            print("Error")
    elif move == "c":
        name = input("Enter the filename\n")
        if MusicServer.setAsCurr(name):
            print("Done")
        else:
            print("Error")
    elif move == "d":
        name = input("Enter the filename\n")
        if MusicServer.delete(name):
            print("Done")
        else:
            print("Error")
    elif move == "p":
        print(MusicServer.curr())
        print(MusicServer.recordings())
    elif move == "f":
        break
MusicServer.stop()