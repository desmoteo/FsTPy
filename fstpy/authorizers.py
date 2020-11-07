import os
import fs 
import sys
from hashlib import md5

import pyftpdlib

class DummyAuthorizer(pyftpdlib.authorizers.DummyAuthorizer):
    """Basic "dummy" authorizer class, suitable for subclassing to
    create your own custom authorizers.
    An "authorizer" is a class handling authentications and permissions
    of the FTP server.  It is used inside FTPHandler class for verifying
    user's password, getting users home directory, checking user
    permissions when a file read/write event occurs and changing user
    before accessing the filesystem.
    DummyAuthorizer is the base authorizer, providing a platform
    independent interface for managing "virtual" FTP users. System
    dependent authorizers can by written by subclassing this base
    class and overriding appropriate methods as necessary.
    """

    read_perms = "elr"
    write_perms = "adfmwMT"

    def __init__(self, fs_url, cred_file=None):
        super().__init__()
        self.fs_url = fs_url
        self.fs = fs.open_fs(fs_url)
        self.user_table = {}
        if cred_file != None:
            with open(cred_file, 'r') as f:
                for l in f.readlines():
                    i = l.split(';')
                    self.add_user(*i)

    def add_user(self, username, password, homedir, perm='elr',
                 msg_login="Login successful.", msg_quit="Goodbye."):
        """Add a user to the virtual users table.
        AuthorizerError exceptions raised on error conditions such as
        invalid permissions, missing home directory or duplicate usernames.
        Optional perm argument is a string referencing the user's
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
        Optional msg_login and msg_quit arguments can be specified to
        provide customized response strings when user log-in and quit.
        """
        if self.has_user(username):
            raise ValueError('user %r already exists' % username)
        if not isinstance(homedir, str):
            homedir = homedir.decode('utf8')
        if not self.fs.isdir(homedir):
            raise ValueError('no such directory: %r' % homedir)

        self.fs = fs.open_fs(self.fs_url+homedir)
        self._check_permissions(username, perm)
        dic = {'pwd': str(password),
               'home': self.fs_url+homedir,
               #'root': self.fs_url+homedir,
               'perm': perm,
               'operms': {},
               'msg_login': str(msg_login),
               'msg_quit': str(msg_quit)
               }
        self.user_table[username] = dic


    def override_perm(self, username, directory, perm, recursive=False):
        """Override permissions for a given directory."""
        self._check_permissions(username, perm)
        if not self.fs.isdir(directory):
            raise ValueError('no such directory: %r' % directory)
        directory = os.path.normcase(os.path.realpath(directory))
        home = os.path.normcase(self.get_home_dir(username))
        if directory == home:
            raise ValueError("can't override home directory permissions")
        if not self._issubpath(directory, home):
            raise ValueError("path escapes user home directory")
        self.user_table[username]['operms'][directory] = perm, recursive


    def has_perm(self, username, perm, path=None):
        """Whether the user has permission over path (an absolute
        pathname of a file or a directory).
        Expected perm argument is one of the following letters:
        "elradfmwMT".
        """
        if path is None:
            return perm in self.user_table[username]['perm']

        path = os.path.normcase(path)
        for dir in self.user_table[username]['operms'].keys():
            operm, recursive = self.user_table[username]['operms'][dir]
            if self._issubpath(path, dir):
                if recursive:
                    return perm in operm
                if (path == dir or os.path.dirname(path) == dir and not
                        self.fs.isdir(path)):
                    return perm in operm

        return perm in self.user_table[username]['perm']


class MD5Authorizer(DummyAuthorizer):

    def validate_authentication(self, username, password, handler):
        _hash = md5(password.encode('utf8')).hexdigest()
        try:
            if self.user_table[username]['pwd'] != _hash:
                raise KeyError
        except KeyError:
            raise pyftpdlib.authorizers.AuthenticationFailed