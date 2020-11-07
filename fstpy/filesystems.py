import os
import fs 
import time
import datetime
import stat
import tempfile
from types import MethodType

try:
    import pwd
    import grp
except ImportError:
    pwd = grp = None

try:
    from stat import filemode as _filemode  # PY 3.3
except ImportError:
    from tarfile import filemode as _filemode

import pyftpdlib
from pyftpdlib._compat import u, unicode, PY3


class AbstractedFS(pyftpdlib.filesystems.AbstractedFS):
    """A class used to interact with the file system, providing a
    cross-platform interface compatible with both Windows and
    UNIX style filesystems where all paths use "/" separator.
    AbstractedFS distinguishes between "real" filesystem paths and
    "virtual" ftp paths emulating a UNIX chroot jail where the user
    can not escape its home directory (example: real "/home/user"
    path will be seen as "/" by the client)
    It also provides some utility methods and wraps around all os.*
    calls involving operations against the filesystem like creating
    files or removing directories.
    FilesystemError exception can be raised from within any of
    the methods below in order to send a customized error string
    to the client.
    """

    def __init__(self, root_fs, cmd_channel):
        """
         - (str) root: the user "real" home directory (e.g. '/home/user')
         - (instance) cmd_channel: the FTPHandler class instance
        """
        # Set initial current working directory.
        # By default initial cwd is set to "/" to emulate a chroot jail.
        # If a different behavior is desired (e.g. initial cwd = root,
        # to reflect the real filesystem) users overriding this class
        # are responsible to set _cwd attribute as necessary.
        self._cwd = u('/')
        self._fs = fs.open_fs(root_fs)
        i = self._fs.getinfo('/', namespaces=['stat', 'lstat', 'details', 'access', 'link'])
        self._has_access_info = i.has_namespace('access')
        self._has_link_info = i.has_namespace('access')
        self._has_stat_info = i.has_namespace('stat')
        self._has_lstat_info = i.has_namespace('lstat')

        if self._has_link_info:
            def readlink(self, path):
                i = self.getinfo(path)
                return i.target
            #setattr(self, "readlink", readlink)
            self.readlink = MethodType(readlink, self)
        else:
            self.readlink = None

        self._root = u('/')#self._fs.root_path 
        self.cmd_channel = cmd_channel

    # --- Pathname / conversion utilities

    def ftpnorm(self, ftppath):
        """Normalize a "virtual" ftp pathname (typically the raw string
        coming from client) depending on the current working directory.
        Example (having "/foo" as current working directory):
        >>> ftpnorm('bar')
        '/foo/bar'
        Note: directory separators are system independent ("/").
        Pathname returned is always absolutized.
        """
        assert isinstance(ftppath, unicode), ftppath
        if os.path.isabs(ftppath):
            p = os.path.normpath(ftppath)
        else:
            p = os.path.normpath(os.path.join(self.cwd, ftppath))
        # normalize string in a standard web-path notation having '/'
        # as separator.
        if os.sep == "\\":
            p = p.replace("\\", "/")
        # os.path.normpath supports UNC paths (e.g. "//a/b/c") but we
        # don't need them.  In case we get an UNC path we collapse
        # redundant separators appearing at the beginning of the string
        while p[:2] == '//':
            p = p[1:]
        # Anti path traversal: don't trust user input, in the event
        # that self.cwd is not absolute, return "/" as a safety measure.
        # This is for extra protection, maybe not really necessary.
        if not os.path.isabs(p):
            p = u("/")
        return p

    def ftp2fs(self, ftppath):
        """Translate a "virtual" ftp pathname (typically the raw string
        coming from client) into equivalent absolute "real" filesystem
        pathname.
        Example (having "/home/user" as root directory):
        >>> ftp2fs("foo")
        '/home/user/foo'
        Note: directory separators are system dependent.
        """
        assert isinstance(ftppath, unicode), ftppath
        # as far as I know, it should always be path traversal safe...
        if os.path.normpath(self.root) == os.sep:
            return os.path.normpath(self.ftpnorm(ftppath))
        else:
            p = self.ftpnorm(ftppath)[1:]
            return os.path.normpath(os.path.join(self.root, p))

    def fs2ftp(self, fspath):
        """Translate a "real" filesystem pathname into equivalent
        absolute "virtual" ftp pathname depending on the user's
        root directory.
        Example (having "/home/user" as root directory):
        >>> fs2ftp("/home/user/foo")
        '/foo'
        As for ftpnorm, directory separators are system independent
        ("/") and pathname returned is always absolutized.
        On invalid pathnames escaping from user's root directory
        (e.g. "/home" when root is "/home/user") always return "/".
        """
        assert isinstance(fspath, unicode), fspath
        if os.path.isabs(fspath):
            p = os.path.normpath(fspath)
        else:
            p = os.path.normpath(os.path.join(self.root, fspath))
        if not self.validpath(p):
            return u('/')
        p = p.replace(os.sep, "/")
        p = p[len(self.root):]
        if not p.startswith('/'):
            p = '/' + p
        return p

    def validpath(self, path):
        """Check whether the path belongs to user's home directory.
        Expected argument is a "real" filesystem pathname.
        If path is a symbolic link it is resolved to check its real
        destination.
        Pathnames escaping from user's root directory are considered
        not valid.
        """
        assert isinstance(path, unicode), path
        root = self.realpath(self.root)
        path = self.realpath(path)
        if not root.endswith(os.sep):
            root = root + os.sep
        if not path.endswith(os.sep):
            path = path + os.sep
        if path[0:len(root)] == root:
            return True
        return False

    # --- Wrapper methods around open() and tempfile.mkstemp

    def open(self, filename, mode):
        """Open a file returning its handler."""
        assert isinstance(filename, unicode), filename
        self._fs.makedirs(os.path.dirname(filename), recreate=True)
        return self._fs.open(filename, mode)

    def mkstemp(self, suffix='', prefix='', dir=None, mode='wb'):
        """A wrap around tempfile.mkstemp creating a file with a unique
        name.  Unlike mkstemp it returns an object with a file-like
        interface.
        """
        class FileWrapper:

            def __init__(self, fd, name):
                self.file = fd
                self.name = name

            def __getattr__(self, attr):
                return getattr(self.file, attr)

        text = 'b' not in mode
        # max number of tries to find out a unique file name
        tempfile.TMP_MAX = 50
        fd, name = tempfile.mkstemp(suffix, prefix, dir, text=text)
        file = os.fdopen(fd, mode)
        return FileWrapper(file, name)

    # --- Wrapper methods around os.* calls

    def chdir(self, path):
        """Change the current directory. If this method is overridden
        it is vital that `cwd` attribute gets set.
        """
        # note: process cwd will be reset by the caller
        assert isinstance(path, unicode), path
        #self._fs = self._fs.mkdir(path)
        self.cwd = self.fs2ftp(path)

    def mkdir(self, path):
        """Create the specified directory."""
        assert isinstance(path, unicode), path
        self._fs.makedir(path)

    def listdir(self, path):
        """List the content of a directory."""
        assert isinstance(path, unicode), path
        return self._fs.listdir(path)

    def listdirinfo(self, path):
        """List the content of a directory."""
        assert isinstance(path, unicode), path
        return self._fs.listdir(path)

    def rmdir(self, path):
        """Remove the specified directory."""
        assert isinstance(path, unicode), path
        self._fs.rmdir(path)

    def remove(self, path):
        """Remove the specified file."""
        assert isinstance(path, unicode), path
        self._fs.remove(path)

    def rename(self, src, dst):
        """Rename the specified src file to the dst filename."""
        assert isinstance(src, unicode), src
        assert isinstance(dst, unicode), dst
        self._fs.move(src, dst)

    def chmod(self, path, mode):
        """Change file/directory mode."""
        #assert isinstance(path, unicode), path
        #if not hasattr(os, 'chmod'):
        #    raise NotImplementedError
        #os.chmod(path, mode)

    def getinfo(self, path):
        """Perform a stat() system call on the given path."""
        # on python 2 we might also get bytes from os.lisdir()
        # assert isinstance(path, unicode), path
        return self._fs.getinfo(path, namespaces=['stat', 'lstat', 'details', 'access', 'link'])        

    def stat(self, path):
        """Perform a stat() system call on the given path."""
        # on python 2 we might also get bytes from os.lisdir()
        # assert isinstance(path, unicode), path
        return self._fs.getinfo(path, namespaces=['stat', 'lstat', 'details', 'access', 'link'])

    def utime(self, path, timeval):
        """Perform a utime() call on the given path"""
        # utime expects a int/float (atime, mtime) in seconds
        # thus, setting both access and modify time to timeval
        return 0#os.utime(path, (timeval, timeval))

    def lstat(self, path):
        """Like stat but does not follow symbolic links."""
        # on python 2 we might also get bytes from os.lisdir()
        # assert isinstance(path, unicode), path
        return self._fs.getinfo(path, namespaces=['stat', 'lstat', 'details', 'access', 'link'])

    # --- Wrapper methods around os.path.* calls

    def isfile(self, path):
        """Return True if path is a file."""
        assert isinstance(path, unicode), path
        return self._fs.isfile(path)

    def islink(self, path):
        """Return True if path is a symbolic link."""
        assert isinstance(path, unicode), path
        return self._fs.islink(path)

    def getlinkinfo(self, info):
        if self._has_link_info:
            return info.is_link
        else:
            return False

    def isdir(self, path):
        """Return True if path is a directory."""
        assert isinstance(path, unicode), path
        return self._fs.isdir(path)

    def getsize(self, path):
        """Return the size of the specified file in bytes."""
        assert isinstance(path, unicode), path
        return self._fs.getsize(path)

    def getmtime(self, path):
        """Return the last modified time as a number of seconds since
        the epoch."""
        assert isinstance(path, unicode), path
        return 0#self._fs.getmtime(path)

    def realpath(self, path):
        """Return the canonical version of path eliminating any
        symbolic links encountered in the path (if they are
        supported by the operating system).
        """
        assert isinstance(path, unicode), path
        return os.path.realpath(path)

    def lexists(self, path):
        """Return True if path refers to an existing path, including
        a broken or circular symbolic link.
        """
        assert isinstance(path, unicode), path
        return self._fs.exists(path)

    # --- Listing utilities

    def format_list(self, basedir, listing, ignore_err=True):
        """Return an iterator object that yields the entries of given
        directory emulating the "/bin/ls -lA" UNIX command output.
         - (str) basedir: the absolute dirname.
         - (list) listing: the names of the entries in basedir
         - (bool) ignore_err: when False raise exception if os.lstat()
         call fails.
        On platforms which do not support the pwd and grp modules (such
        as Windows), ownership is printed as "owner" and "group" as a
        default, and number of hard links is always "1". On UNIX
        systems, the actual owner, group, and number of links are
        printed.
        This is how output appears to client:
        -rw-rw-rw-   1 owner   group    7045120 Sep 02  3:47 music.mp3
        drwxrwxrwx   1 owner   group          0 Aug 31 18:50 e-books
        -rw-rw-rw-   1 owner   group        380 Sep 02  3:40 module.py
        """
        @pyftpdlib.filesystems._memoize
        def get_user_by_uid(uid):
            return self.get_user_by_uid(uid)

        @pyftpdlib.filesystems._memoize
        def get_group_by_gid(gid):
            return self.get_group_by_gid(gid)

        assert isinstance(basedir, unicode), basedir
        if self.cmd_channel.use_gmt_times:
            timefunc = time.gmtime
        else:
            timefunc = time.localtime
        SIX_MONTHS = 180 * 24 * 60 * 60
       
        now = time.time()
        for basename in listing:
            if not PY3:
                try:
                    file = os.path.join(basedir, basename)
                except UnicodeDecodeError:
                    # (Python 2 only) might happen on filesystem not
                    # supporting UTF8 meaning os.listdir() returned a list
                    # of mixed bytes and unicode strings:
                    # http://goo.gl/6DLHD
                    # http://bugs.python.org/issue683592
                    file = os.path.join(bytes(basedir), bytes(basename))
                    if not isinstance(basename, unicode):
                        basename = unicode(basename, 'utf8', 'ignore')
            else:
                file = os.path.join(basedir, basename)
            try:
                st = self.lstat(file)
            except (OSError, pyftpdlib.filesystems.FilesystemError):
                if ignore_err:
                    continue
                raise

            perms = _filemode(st.get('lstat', 'st_mode')  if self._has_lstat_info else 664)  # permissions
            nlinks = st.get('lstat', 'st_nlink')  if self._has_lstat_info else None  # number of links to inode
            if not nlinks:  # non-posix system, let's use a bogus value
                nlinks = 1
            size = st.size  # file size
            uname = get_user_by_uid(os.getuid())
            gname = get_group_by_gid(os.getgid())
            mtime = timefunc(datetime.datetime.timestamp((st.modified)))
            # if modification time > 6 months shows "month year"
            # else "month hh:mm";  this matches proftpd format, see:
            # https://github.com/giampaolo/pyftpdlib/issues/187
            if (now - datetime.datetime.timestamp((st.modified))) > SIX_MONTHS:
                fmtstr = "%d  %Y"
            else:
                fmtstr = "%d %H:%M"
            try:
                mtimestr = "%s %s" % (pyftpdlib.filesystems._months_map[mtime.tm_mon],
                                      time.strftime(fmtstr, mtime))
            except ValueError:
                # It could be raised if last mtime happens to be too
                # old (prior to year 1900) in which case we return
                # the current time as last mtime.
                mtime = timefunc()
                mtimestr = "%s %s" % (pyftpdlib.filesystems._months_map[mtime.tm_mon],
                                      time.strftime("%d %H:%M", mtime))

            # same as stat.S_ISLNK(st.st_mode) but slighlty faster
            #islink = (st.st_mode & 61440) == stat.S_IFLNK
            islink = self.getlinkinfo(st)#st.islink
            if islink and self.readlink is not None:
                # if the file is a symlink, resolve it, e.g.
                # "symlink -> realfile"
                try:
                    basename = basename + " -> " + self.readlink(file)
                except (OSError, pyftpdlib.filesystems.FilesystemError):
                    if not ignore_err:
                        raise

            # formatting is matched with proftpd ls output
            line = "%s %3s %-8s %-8s %8s %s %s\r\n" % (
                perms, nlinks, uname, gname, size, mtimestr, basename)
            yield line.encode('utf8', self.cmd_channel.unicode_errors)

    def format_mlsx(self, basedir, listing, perms, facts, ignore_err=True):
        """Return an iterator object that yields the entries of a given
        directory or of a single file in a form suitable with MLSD and
        MLST commands.
        Every entry includes a list of "facts" referring the listed
        element.  See RFC-3659, chapter 7, to see what every single
        fact stands for.
         - (str) basedir: the absolute dirname.
         - (list) listing: the names of the entries in basedir
         - (str) perms: the string referencing the user permissions.
         - (str) facts: the list of "facts" to be returned.
         - (bool) ignore_err: when False raise exception if os.stat()
         call fails.
        Note that "facts" returned may change depending on the platform
        and on what user specified by using the OPTS command.
        This is how output could appear to the client issuing
        a MLSD request:
        type=file;size=156;perm=r;modify=20071029155301;unique=8012; music.mp3
        type=dir;size=0;perm=el;modify=20071127230206;unique=801e33; ebooks
        type=file;size=211;perm=r;modify=20071103093626;unique=192; module.py
        """
        assert isinstance(basedir, unicode), basedir
        if self.cmd_channel.use_gmt_times:
            timefunc = time.gmtime
        else:
            timefunc = time.localtime
        permdir = ''.join([x for x in perms if x not in 'arw'])
        permfile = ''.join([x for x in perms if x not in 'celmp'])
        if ('w' in perms) or ('a' in perms) or ('f' in perms):
            permdir += 'c'
        if 'd' in perms:
            permdir += 'p'
        show_type = 'type' in facts
        show_perm = 'perm' in facts
        show_size = 'size' in facts
        show_modify = 'modify' in facts
        show_create = 'create' in facts
        show_mode = 'unix.mode' in facts
        show_uid = 'unix.uid' in facts
        show_gid = 'unix.gid' in facts
        show_unique = 'unique' in facts
        for basename in listing:
            retfacts = dict()
            if not PY3:
                try:
                    file = os.path.join(basedir, basename)
                except UnicodeDecodeError:
                    # (Python 2 only) might happen on filesystem not
                    # supporting UTF8 meaning os.listdir() returned a list
                    # of mixed bytes and unicode strings:
                    # http://goo.gl/6DLHD
                    # http://bugs.python.org/issue683592
                    file = os.path.join(bytes(basedir), bytes(basename))
                    if not isinstance(basename, unicode):
                        basename = unicode(basename, 'utf8', 'ignore')
            else:
                file = os.path.join(basedir, basename)
            # in order to properly implement 'unique' fact (RFC-3659,
            # chapter 7.5.2) we are supposed to follow symlinks, hence
            # use os.stat() instead of os.lstat()
            try:
                st = self.stat(file)
            except (OSError, pyftpdlib.filesystems.FilesystemError):
                if ignore_err:
                    continue
                raise
            # type + perm
            # same as stat.S_ISDIR(st.st_mode) but slightly faster
            isdir = st.is_dir#(st.st_mode & 61440) == stat.S_IFDIR
            if isdir:
                if show_type:
                    if basename == '.':
                        retfacts['type'] = 'cdir'
                    elif basename == '..':
                        retfacts['type'] = 'pdir'
                    else:
                        retfacts['type'] = 'dir'
                if show_perm:
                    retfacts['perm'] = permdir
            else:
                if show_type:
                    retfacts['type'] = 'file'
                if show_perm:
                    retfacts['perm'] = permfile
            if show_size:
                retfacts['size'] = st.size  # file size
            # last modification time
            if show_modify:
                try:
                    retfacts['modify'] = time.strftime("%Y%m%d%H%M%S",
                                                       timefunc(datetime.datetime.timestamp((st.modified))))
                # it could be raised if last mtime happens to be too old
                # (prior to year 1900)
                except ValueError:
                    pass
            if show_create:
                # on Windows we can provide also the creation time
                try:
                    retfacts['create'] = time.strftime("%Y%m%d%H%M%S",
                                                       timefunc(datetime.datetime.timestamp(st.modified)))
                except ValueError:
                    pass
            # UNIX only
            if show_mode:
                retfacts['unix.mode'] = oct(st.get('lstat', 'st_mode') & 511) if self._has_lstat_info else 664#oct(st.st_mode & 511)
            if show_uid:
                retfacts['unix.uid'] = st.uid if self._has_lstat_info else os.getuid()#st.st_uid
            if show_gid:
                retfacts['unix.gid'] = st.gid if self._has_lstat_info else os.getgid()#st.st_gid

            # We provide unique fact (see RFC-3659, chapter 7.5.2) on
            # posix platforms only; we get it by mixing st_dev and
            # st_ino values which should be enough for granting an
            # uniqueness for the file listed.
            # The same approach is used by pure-ftpd.
            # Implementors who want to provide unique fact on other
            # platforms should use some platform-specific method (e.g.
            # on Windows NTFS filesystems MTF records could be used).
            if show_unique:
                retfacts['unique'] = "%xg%x" % (st.get('lstat', 'st_dev') if self._has_lstat_info else 0, st.get('lstat', 'st_ino') if self._has_lstat_info else 0)

            # facts can be in any order but we sort them by name
            factstring = "".join(["%s=%s;" % (x, retfacts[x])
                                  for x in sorted(retfacts.keys())])
            line = "%s %s\r\n" % (factstring, basename)
            yield line.encode('utf8', self.cmd_channel.unicode_errors)
