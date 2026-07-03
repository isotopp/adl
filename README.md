# ADL

Download ebooks from Adobe `.acsm` files and transfer them to your ebook reader.

ADL provides basic command-line functions for books protected by Adobe ADEPT DRM. Adobe Digital Editions supports Windows, macOS, and Android, but not Linux. This tool provides similar download and device activation workflows from the command line.

ADL does not remove DRM.

## What It Does

- Log in with your Adobe ID, or as anonymous with restrictions.
- Activate a new ebook reader that supports Adobe ADEPT DRM.
- Download an EPUB from an ACSM file.

If your book is protected by DRM, ADL downloads an encrypted EPUB. A device activated with the same user used to download the book can read that encrypted file after you copy it to the device.

## What It Does Not Do

- Remove DRM from your book.
- Copy downloaded books to your device automatically.

## Disclaimer

This tool is suited above all to the original author's purpose. It has not been tested extensively or across many setups. Use it at your own risk.

## Requirements

- Python 3.9+
- [uv](https://docs.astral.sh/uv/)

Install dependencies and create the virtual environment:

```sh
uv sync
```

## Usage

### Log In

```sh
uv run adl login -u <adobeID>
```

You only need to log in once to exchange encryption keys.

Using an Adobe ID is recommended. Anonymous login is possible, but you may lose access to your book if something goes wrong during download or if you lose the private key. With an Adobe ID, keys and books are attached to your account, so you can log in elsewhere and recover them.

You can log in several times if you have several accounts.

### Download a Book

```sh
uv run adl get -f <file.acsm>
```

### Manage Accounts

List known accounts:

```sh
uv run adl account list
```

Select the account to use:

```sh
uv run adl account use <account urn>
```

### Activate a Device

Mount the root of your device somewhere, select the account you want to use, then run:

```sh
uv run adl device register <mountpoint>
```

Several cases may occur:

- The device has never been activated with ADE or ADL: ADL activates the device.
- The device has already been activated for your user: nothing is changed on the device, but ADL's database is updated.
- The device has already been activated for an unknown user: nothing is changed, to avoid losing access to books on the device.

### Transfer the Downloaded Book

ADL does not yet copy books to devices. Copy the downloaded EPUB to the device filesystem manually. On many readers, books can be placed anywhere.

## License

ADL is published under the GPLv3.
