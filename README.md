### Work in progress
The API and used specifications haven't been decided on yet and are subject to change.

---

# ConfBundler
ConfBundler is an agent-less, declarative configuration framework, aiming to simplify and unify set-up of hosts
managed using different tools. This is achieved by defining a stable, declarative manifest format, which can then be translated into native formats of host-specific configuration tooling.

## Usage
Currently, the only supported input and output formats are YAML and Tar respectively.

An example:

``` 
python3 -m confbundler samples/ssh ssh-bundle.tar
ssh root@configured-host tar --xattrs -xvC / < ssh-bundle.tar
```

Here, a manifest file at `samples/ssh/manifest.yaml` is used to generate a Tar archive, which is then transferred and extracted on the root filesystem of the target. No additional target-side tools are needed in order to deploy the generated Tar bundle.