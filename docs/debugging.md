# Debugging

In the dev environment (built by default) we install [remote-pdb](https://pypi.org/project/remote-pdb/). 

We also set environment variables for integrating with pythons `breakpoint` so you can just add a line anywhere needed like:
```
breakpoint()
```


When the code hits that point it should stop and start remote-pdb on port 4444. This port is exposed through the container.

You can use any method you like to connect to remote-pdb (see remote-pdb docs for ideas).
