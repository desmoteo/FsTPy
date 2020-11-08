# FsTPy
Bridging FTP servers and cloud storage.


FsTPy brings together the power and scalability of pyftpdlib (https://github.com/giampaolo/pyftpdlib) with the flexibility and abstraction provided by PyFilesystem2 (https://github.com/PyFilesystem/pyfilesystem2).

It allows to build custom FTP and FTPS servers on abstracted filesystem (local or cloud such as S3 or Dropbox or Google Drive)

## Installation 

Install from pypi with pip:

```bash
pip3 install FsTPy
```

## Standalone Server

The package comes with an executable server which can be used as a starting point for custom solutions. The script reqires to be executed in a folder containing three files

* credentials.txt a file with login information 
* server.key SSL key of the server
* server.crt Certificate of the server

Server key and certificate can be generated following the guide https://httpd.apache.org/docs/2.4/ssl/ssl_faq.html#selfcert or any similar proecdure.

The credentials file credentials.txt should be formatted as follows

### credentials.txt
This files contains a column separated list of username, md5 password hash, root directory, user permissions permissions and optional login and logout messages.
Different lines can be defined in order to define different user credentials. 

The following example of credentials.txt defines two users with the same password (12345) but different permissions.

```bash
user1;827ccb0eea8a706c4c34a16891f84e7b;/;elradfmwMT;Welcome, user1!;Bye, bye user1
user2;827ccb0eea8a706c4c34a16891f84e7b;/;elr;Welcome, user2!;Bye, bye user2
```

#### User Permissions

Permission argument is a string referencing the user's
permissions explained below:

Read permissions:
 - "e" = change directory (CWD command)
 - "l" = list files (LIST, NLST, STAT, MLSD, MLST, SIZE, MDTM commands)
 - "r" = retrieve file from the server (RETR command)

Write permissions:
 - "a" = append data to an existing file (APPE command)
 - "d" = delete file or directory (DELE, RMD commands)
 - "f" = rename file or directory (RNFR, RNTO commands)
 - "m" = create directory (MKD command)
 - "w" = store a file to the server (STOR, STOU commands)
 - "M" = change file mode (SITE CHMOD command)
 - "T" = update file last modified time (MFMT command)

### Running the server
Once installed, the server can be run simply by providing the PyFilesystem2 URL of the desired filesystem .
In order to start an S3 backed FTPS server on bucket my-bucket:

1. Install S3 extension for PyFilesysytem2:
```bash
pip3 install fs-s3fs
```
2. Run the server on the desired S3 bucket:
```bash
fstpyd 's3://my-bucket/'
```

The server binds to 0.0.0.0:2121. See help to change the address and port arguments:
```bash
fstpyd --help
```
## APIs

The API is pretty simple. It extends some classes of the pyftpdlib library (https://github.com/giampaolo/pyftpdlib). The fstpyd script (https://github.com/desmoteo/FsTPy/blob/main/scripts/fstpyd) can be used to understand basic usage, in combination with the rich documentation of pyftpdlib (https://pyftpdlib.readthedocs.io/en/latest/index.html) and PyFilesystem2 (https://docs.pyfilesystem.org/en/latest/index.html)


