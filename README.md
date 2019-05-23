[![Python 3.7](https://img.shields.io/badge/Python-3.7+-informational.svg?logoColor=white&logo=python&style=popout)](https://www.python.org/)

![Developed on Arch](https://img.shields.io/badge/Built%20and%20Tested%20on-Arch%20Linux-informational.svg?logoColor=%231793D1&logo=arch-linux&style=popout)

[![Codestyle: Black](https://img.shields.io/badge/Codestyle-Black-000000.svg)](https://github.com/ambv/black)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-green.svg)](https://opensource.org/licenses/GPL-3.0)

# EZ-IPC

Interprocess Communication, Easily.

I dont know what Im doing.

---

The goal of this Library is to simplify IPC, possibly networked, as much as possible. A Server instance of the program will listen for connections, accept connections from Client instances of the program, and then allow for the transfer of Python data via [JSON-RPC](https://www.jsonrpc.org/specification).

As a developer with a long standing aversion to application layer networking, I will be learning the basics while building this. I have no idea what limitations will be involved, but still I intend the Library to be as accessible, and also secure, as I can possibly make it.

*\*Due to my inexperience, any and all data transferred by way of this Library should be considered compromised. Do not use it for anything sensitive.*

## Usage

The Server instance is surprisingly simple, if it is not needed for any other asynchronous code at the same time. All you need to do is instantiate the Server class, define and hook any callback coroutines you want to run, and then call the `Server.start()` method.

```python
from ezipc.server import Server

serv = Server()  # Instantiate a Server.

async def write_file(data, conn):
    # Define a Coroutine that will be called with the relevant Request. The
    #   Coroutine should take two Arguments:
    #       `data` - A JSON-RPC Message, in the form of a Dict
    #       `conn` - The Tunnel object that received the Message
    print("Writing data received from Remote {} to file...".format(conn.id))
    try:
        with open(data["params"]["filename"], "w") as file:
            written = file.write(data["params"]["content"])
    except (KeyError, ValueError):
        # For a Request, the JSON-RPC protocol would dictate that a Response is
        #   returned with an error code from here.
        print("Failed to write file.")
    else:
        print("Written {} bytes to file.".format(written))


# Now that we have a Coroutine to handle any incoming data, we should
#   hook the Coroutine to an RPC method; For this example, we will use a
#   Notification for a method called "write", because a Notification
#   does not expect any return.
serv.hook_notif("WRITE", write_file)


# Now we have a Server, ready to go live and start listening.
serv.start()
```

And just like that, the Server is listening for Messages. However, this simplicity comes at a small cost: The `Server.start()` method calls `asyncio.run()`, which means that no other asynchronous code can be run on this thread.

If you need the Server to run in the background while you do other things, you will need to use `await asyncio.create_event()` on the `Server.run()` Coroutine. This means you must manage your own Event Loop, which cuts down slightly on the EZ in EZ-IPC.

The Client instance is *somewhat* more complex, as it typically is not the party that gets to wait around. I think I have made it elegant enough, but in addition to defining Coroutines for what to send, if any Message you send is a Request, you must be prepared to deal with the Response.

This requires you to define a second Coroutine, and then (inside your first Coroutine) read the Message UUID assigned to the Requests you send, and hook those UUIDs to your second Coroutine, the Response handler. If this is not clear, refer to the test method in `__init__.py` for an example.
