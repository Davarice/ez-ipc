[![License: GPLv3](assets/gplv3-127x51.png)](https://opensource.org/licenses/GPL-3.0)

[![Python 3.7](https://img.shields.io/badge/Python-3.7+-informational.svg?logoColor=white&logo=python&style=popout)](https://www.python.org/)
[![Codestyle: Black](https://img.shields.io/badge/Codestyle-Black-000000.svg)](https://github.com/ambv/black)

![Developed on Arch](https://img.shields.io/badge/Built%20and%20Tested%20on-Arch%20Linux-informational.svg?logoColor=%231793D1&logo=arch-linux&style=popout)


# EZ-IPC

Interprocess Communication, Easily.

The goal of this Library is to simplify IPC, possibly networked, as much as possible. A Server instance of the program will listen for connections, accept connections from Client instances of the program, and then allow for the transfer of Python data via [JSON-RPC](https://www.jsonrpc.org/specification).

As a developer with a long standing aversion to application layer networking, I will be learning the basics while building this. I have no idea what limitations will be involved, but still I intend the Library to be as accessible, and also secure, as I can possibly make it.

*\*Due to my inexperience, any and all data transferred by way of this Library should be considered compromised. Do not use it for anything sensitive.*

## Usage

The Server instance is surprisingly simple, if it is not needed for any other asynchronous code at the same time. All you need to do is instantiate the Server class, define and hook any callback coroutines you want to run, and then call the `Server.start()` method.

```python
from ezipc.server import Server


serv = Server()  # Instantiate a Server.


async def write_file(data, remote):
    # Define a Coroutine that will be called with the relevant
    #   Notification. The Coroutine should take two Arguments:
    #       `data` - A JSON-RPC Message, in the form of a Dict
    #       `remote` - The Remote object that received the Message
    print("Writing data received from {} to file...".format(remote))
    try:
        with open(data["params"]["filename"], "w") as file:
            written = file.write(data["params"]["content"])
    except (KeyError, OSError, ValueError):
        # For a Request, the JSON-RPC protocol would dictate that a
        #   Response is returned with an "error" field from here.
        print("Failed to write file.")
    else:
        # For a Request, again the protocol dictates a Response would be
        #   returned. For a successful Request, it would include a
        #   "result" field.
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

If you need the Server to run in the background while you do other things, you will need to add the `Server.run()` Coroutine to an Event Loop. This means you must manage your own Event Loop, which cuts down slightly on the EZ in EZ-IPC.

The Client instance is *somewhat* more complex, as it typically is not the party that gets to wait around. I think I have made it elegant enough, but in addition to defining Coroutines for what to send, if any Message you send is a Request, you must be prepared to deal with the Response.

This requires you to either:
1. Save the Future object returned by `Remote.request()`, and `await` it later. This will allow the same Coroutine to be "paused" until it has a Response.
2. Define a second Function, and then (inside your first Coroutine) pass the Function into the `Remote.request()` Coroutine as a third argument, after the Method and Parameters. It will be called when a Response is received, with the Future from the Request passed as the first argument. The `partial()` function from `functools` can be used to pass in more arguments.
