import asyncio
import fastmcp

client = fastmcp.Client("http://127.0.0.1:8000/mcp")

async def main():
    async with client:
        await client.ping()
        while True:
            move = input("r to record, p to play, s to save, c to set as curr, d to delete, l to print, f to finish\n")
            if move == "r":
                input("Enter to start recording\n")
                await client.call_tool("startRecording", {})
                input("Enter to stop recording\n")
                await client.call_tool("stopRecording", {})
                print("Done")
            elif move == "p":
                input("Enter to start playing\n")
                await client.call_tool("startPlaying", {})
                input("Enter to stop playing\n")
                await client.call_tool("stopPlaying", {})
                print("Done")
            elif move == "s":
                name = input("Enter the filename\n")
                if (await client.call_tool("saveCurr", {"name" : name})).data:
                    print("Done")
                else:
                    print("Error")
            elif move == "c":
                name = input("Enter the filename\n")
                if (await client.call_tool("setAsCurr", {"name" : name})).data:
                    print("Done")
                else:
                    print("Error")
            elif move == "d":
                name = input("Enter the filename\n")
                if (await client.call_tool("delete", {"name" : name})).data:
                    print("Done")
                else:
                    print("Error")
            elif move == "l":
                print((await client.read_resource("data://curr"))[0].text)
                print((await client.read_resource("data://recordings"))[0].text)
            elif move == "f":
                break

if __name__ == "__main__":
    asyncio.run(main())