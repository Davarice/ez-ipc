import asyncio


def client_test():
    from .client import Client

    async def receive(data):
        print("Received Server response: {}".format(repr(data)))

    async def go(_client):
        print("Sending Requests in three seconds.")

        for i in ["aaaa", "zxcv", "qwert"]:
            await asyncio.sleep(3)

            print("Sending...")
            uuid, ts = await _client.con.request("ping", [i])
            _client.con.hook_response(uuid.hex, receive)

            print("Request sent.")
        await asyncio.sleep(1)

    Client().run_through(go)


def server_test():
    from .server import Server
    Server().start()
