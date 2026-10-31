import asyncio, aiohttp, time, sys
URL = sys.argv[1]
async def main():
    t = time.time()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(URL, timeout=90) as ws:
                print("OK: WS mo duoc sau", round(time.time()-t,1), "s")
    except Exception as e:
        print("LOI:", type(e).__name__, e, "sau", round(time.time()-t,1), "s")
asyncio.run(main())
