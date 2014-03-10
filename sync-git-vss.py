###############################################################################
# A Python script to synchronise a VSS project with a git branch.             #
# Makes use of Windows-specific commands.                                     #
###############################################################################
# Assumptions:                                                                #
#   * Both {ss,git}.exe are in %PATH%;                                        #
#   * %SSPATH% contains the VSS database location---where srcsafe.ini is;     #
#   * Commands used to collect git snapshot produce a directory listing with  #
#     one file/sub-directory per line;                                        #
#   * The VSS user of this script does not have the VSS project checked out   #
#     externally (used in error_ckout).                                       #
#                                                                             #
# Parameters:                                                                 #
#   #1  git url w/ user and pass, e.g., https://user:pwd@bitbucket.org/...git;#
#   #2  git branch;                                                           #
#   #3  VSS project;                                                          #
#   #4  VSS user;                                                             #
#   #5  VSS user password;                                                    #
#  [#6  Optional git tag.]                                                    #
#                                                                             #
# High-level description:                                                     #
#   1. Clone the git branch to a temporary directory;                         #
#   2. Take a snapshot Sgit of the directory structure;                       #
#   3. Checkin modified files to VSS:                                         #
#       3.1. Checkout the VSS project without overwritting local files;       #
#       3.2. Checkin the VSS project;                                         #
#   4. Take a snapshot Svss of the directory structure;                       #
#   5. Add/delete in VSS files added/removed in git:                          #
#       5.1. From Sgit obtain the set of files Fgit;                          #
#       5.2. From Svss obtain the set of files Fvss;                          #
#       5.3. Delete from VSS each f in Fvss and not in Fgit;                  #
#       5.4. Add to VSS each f in Fgit and not in Fvss;                       #
#   6. Add/delete in vss sub-directories added/removed in git:                #
#       6.1. From Sgit obtain the set of sub-directories Dgit;                #
#       6.2. From Svss obtain the set of sub-directories Dvss;                #
#       6.3. Delete from VSS each d in Dvss and not in Dgit;                  #
#       6.4. Add to VSS each d in Dgit and not in Dvss;                       #
#       6.5. Apply steps 4-6 to each d in Dgit and Dvss;                      #
#                                                                             #
# VSS limitations:                                                            #
#    Project paths can be up to 259 characters long, including the file name. #
#        see http://msdn.microsoft.com/en-us/library/ms181045(v=vs.80).aspx   #
###############################################################################

###############################################################################
# imports                                                                     #
###############################################################################
import sys
import os
import tempfile
import shutil
import subprocess
import time
###############################################################################
# helper functions---preconditions                                            #
###############################################################################
def error_sspath():
    print ("Error while reading SSPATH environment variable: not set")
    print ("Please point SSPATH to the directory of your VSS database, e.g., set SSPATH=C:\VSS-database")
def error_args():
    print ("Error while parsing argument list: insufficient arguments")
def error_help():
    print ("Usage: python {} git_url git_branch vss_proj vss_user vss_pwd [git_tag]".format(sys.argv[0]))
    print ("Parameters:")
    print ("       git_url: git repository's URL with user and password, e.g., https://user:passwd@bitbucket.org/owner/repo.git")
    print ("    git_branch: git repository's branch to synchronise")
    print ("      vss_proj: vss project to be synchronised with git repository's branch")
    print ("      vss_user: vss username for authentication")
    print ("       vss_pwd: vss user's password for authentication")
    print ("       git_tag: tag to apply to the synchronised git branch [optional]")
    print ("Example:")
    print ("    python {} https://palves:passwd@bitbucket.org/owner/repo.git master $/Project palves passwd [1.0]".format(sys.argv[0]))
    print ("Please ensure that:")
    print ("    both git.exe and ss.exe are in PATH")
    print ("    SSPATH is set to the VSS database directory---where srcsafe.ini is")
    print ("    the vss_user does not have the project currently checked out")
###############################################################################
# script preconditions                                                        #
###############################################################################
if os.environ.get("SSPATH") is None:
    error_sspath()
    error_help()
    sys.exit()
if len(sys.argv) < 6:
    error_args()
    error_help()
    sys.exit()
###############################################################################
# cli arguments                                                               #
###############################################################################
use_git_tag = False
base_dir    = sys.argv[1]
git_repo    = sys.argv[2]
git_branch  = sys.argv[3]
vss_proj    = sys.argv[4]
vss_user    = sys.argv[5]
vss_passwd  = sys.argv[6]
if len(sys.argv) == 8:
    use_git_tag = True
    git_tag     = sys.argv[7]
###############################################################################
# vss-specific environment variables                                          #
###############################################################################
os.environ["SSDIR"]  = os.environ["SSPATH"]
os.environ["SSUSER"] = vss_user
os.environ["SSPWD"]  = vss_passwd
###############################################################################
# git snapshot                                                                #
###############################################################################
git_snap_files   = dict()
git_snap_subdirs = dict()
###############################################################################
# windows-specific shell command templates                                    # 
###############################################################################
cmd_win_dir_files = "dir /A:-D /B"
cmd_win_dir_dirs  = "dir /A:D /B"
cmd_win_del_dir   = "rm -rf {}"
###############################################################################
# git command templates                                                       #
###############################################################################
cmd_git_clone = "git clone {} {}"
cmd_git_ckout = "git checkout {}"
cmd_git_pull  = "git pull origin"
cmd_git_tag   = "git tag {}"
cmd_git_push  = "git push --tags origin"
###############################################################################
# vss command templates                                                       #
###############################################################################
cmd_vss_cp        = "ss cp {}"
cmd_vss_dir       = "ss dir -F"
cmd_vss_get       = "ss get {}"
cmd_vss_add       = "ss add {} -R -C- -I-"
cmd_vss_del       = "ss delete {} -S -I-Y"
cmd_vss_ckin      = "ss checkin {} -R -C-"
cmd_vss_ckout     = "ss checkout {} -R -G-"
cmd_vss_undockout = "ss undocheckout {} -R -G-"
cmd_vss_rename    = "ss rename {} {} -S"
cmd_vss_proj      = "ss project"
###############################################################################
# vss error return codes                                                      #
###############################################################################
err_vss = 100
ok_vss  = 0
pathlen_vss = 259
###############################################################################
# helper functions---path length                                              #
###############################################################################
def trunc_path(path, obj):
	full_path = path + "/" + obj
	len_fullpath = len(full_path)
	len_obj = len(obj)
	trunc = (len_fullpath + 10) - pathlen_vss
	return len(obj) - trunc
def check_path(path, obj):
	full_path = path + "/" + obj
	len_fullpath = len(full_path)
	trunc = trunc_path(path, obj)
	if len_fullpath > pathlen_vss or trunc < 0:
		error_pathlen(full_path)
		sys.exit()
def parse_path(fn):
    with open(fn, "rU") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                # Current project is $/...
                # \_______19________/
                return stripped[:19]
def current_path():
    result = ""
    # redirect list output to a temporary file, parse path and
    # remove temporary file
    fd, fn = tempfile.mkstemp()
    try:
        subprocess.check_call(vss_proj, stdout=fd, stderr=fd, shell=True)
        os.close(fd)
        result = parse_path(fn)
    except subprocess.CalledProcessError:
        os.close(fd)
    os.remove(fn)
    return result
###############################################################################
# helper functions---git snapshot                                             #
###############################################################################
def parse_files_cwd(files, fn):
    with open(fn, "rU") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                check_path(current_path(), stripped)
                files.append(stripped)
def parse_subdirs_cwd(subdirs, fn):
    with open(fn, "rU") as f:
        for line in f:
            stripped = line.strip()
            if stripped and stripped != ".git":
                check_path(current_path(), stripped)
                subdirs.append(stripped)
def parse_cwd(sh_cmd, parse_fun):
    result = []
    # redirect list output to a temporary file, parse names into list and
    # remove temporary file
    fd, fn = tempfile.mkstemp()
    try:
        subprocess.check_call(sh_cmd, stdout=fd, stderr=fd, shell=True)
        os.close(fd)
        parse_fun(result, fn)
    except subprocess.CalledProcessError:
        os.close(fd)
    os.remove(fn)
    return result
def create_git_snap(dir):
    os.chdir(dir)
    files   = parse_cwd(cmd_win_dir_files, parse_files_cwd)
    subdirs = parse_cwd(cmd_win_dir_dirs, parse_subdirs_cwd)
    # populate snapshot
    git_snap_files[os.getcwd()]   = files
    git_snap_subdirs[os.getcwd()] = subdirs
    # apply recursively
    for d in subdirs:
        create_git_snap(d)
    os.chdir("..")
###############################################################################
# helper functions---vss snapshot                                             #
###############################################################################
def parse_vss_cwd_is_file(str):
    return str and \
            str.startswith("$", 0, 1) == False and \
            str.endswith("item(s)") == False and \
            str.startswith("No items found under") == False
def parse_vss_cwd_is_dir(str):
    return str.startswith("$", 0, 1) == True
def parse_vss_cwd(files, subdirs, fn):
    # output to parse is as follows:
    # a. empty directory:
    #   $/<projname>
    #   No items found under ...
    # b. otherwise:
    #   $/<projname>
    #   (<filename> | $<dirname>)+
    #
    #   <n> items(s)
    with open(fn, "rU") as f:
        first_line = True
        for line in f:
            # skip first line
            if first_line:
                first_line = False
                continue
            stripped = line.strip()
            if parse_vss_cwd_is_file(stripped):
                files.append(stripped)
            else:
                if parse_vss_cwd_is_dir(stripped):
                    # get dirname (after $)
                    before, sep, after = stripped.partition("$")
                    subdirs.append(after)
def create_vss_snap_cwd():
    files   = []
    subdirs = []
    # redirect list output to a temporary file, parse names into the respective
    # list and remove temporary file
    fd, fn = tempfile.mkstemp()
    subprocess.call(cmd_vss_dir, stdout=fd, shell=True)
    os.close(fd)
    parse_vss_cwd(files, subdirs, fn)
    os.remove(fn)
    return files, subdirs
###############################################################################
# helper functions                                                            #
###############################################################################
def sync_files(vss_files):
    # get list of files to add/remove
    try:
        git_files = git_snap_files[os.getcwd()]
    except KeyError:
        # when we are in a directory to be removed from vss
        git_files = []
    files_to_add = list(set(git_files) - set(vss_files))
    files_to_rem = list(set(vss_files) - set(git_files))
    for f in files_to_add:
        code = subprocess.call(cmd_vss_add.format(f), shell=True)
        if code == err_vss:
            # what if 'f' is checked out?
            subprocess.call(cmd_vss_ckout.format(f), shell=True)
            subprocess.call(cmd_vss_ckin.format(f), shell=True)
    for f in files_to_rem:
        # rename to ftimestamp
        ts = str(time.time())[:10]
        trunc = trunc_path(current_path(), f)
        if trunc >= 0:
            f_trunc = f[:trunc]
            f_ts = f_trunc + ts
        else:
            f_ts = ts[:len(f)]
        subprocess.call(cmd_vss_rename.format(f, f_ts), shell=True)
        subprocess.call(cmd_vss_del.format(f_ts), shell=True)
def sync_dirs(vss_dirs):
    # get list of directories to add/remove
    try:
        git_dirs = git_snap_subdirs[os.getcwd()]
    except KeyError:
        # when we are in a directory to be removed from vss
        git_dirs = []
    dirs_to_add = list(set(git_dirs) - set(vss_dirs))
    dirs_to_rem = list(set(vss_dirs) - set(git_dirs))
    dirs_to_rec = list(set(vss_dirs) & set(git_dirs))
    for d in dirs_to_add:
        subprocess.call(cmd_vss_add.format(d), shell=True)
    for d in dirs_to_rem:
        # we apply recursively because deleting a directory with files prompts
        # user input from vss regarding checkout operations from different
        # sources
        sync_git_vss(d, d)
        subprocess.call(cmd_vss_undockout.format(d), shell=True)
        # rename to dtimestamp
        ts = str(time.time())[:10]
        trunc = trunc_path(current_path(), d)
        if trunc >= 0:
            d_trunc = d[:trunc]
            d_ts = d_trunc + ts
        else:
            d_ts = ts[:len(d)]
        subprocess.call(cmd_vss_rename.format(d, d_ts), shell=True)
        subprocess.call(cmd_vss_del.format(d_ts), shell=True)
    return dirs_to_rec
def sync_git_vss(vss_proj, dir):
    # set vss project and change cwd to 'dir'
    subprocess.call(cmd_vss_cp.format(vss_proj), shell=True)
    os.chdir(dir)
    vss_files, vss_dirs = create_vss_snap_cwd()
    sync_files(vss_files)
    git_vss_dirs = sync_dirs(vss_dirs)
    for d in git_vss_dirs:
        sync_git_vss(d, d)
    subprocess.call(cmd_vss_cp.format(".."), shell=True)
    os.chdir("..")
###############################################################################
# helper functions---rollback on error                                        #
###############################################################################
def error_ckout():
    print ("Error while checking out from VSS (check above for the problem)")
    # answer yes to undo the check out of files that have been modified/removed
    # in git
    cmd = cmd_vss_undockout + " " + "-I-Y"
    subprocess.call(cmd.format(vss_proj), stdout=subprocess.DEVNULL, shell=True)
def error_pathlen(path):
	print ('Error while parsing "'+path+':" length is > '+pathlen_vss)
	print ("Please rename to a path that does not violate the limitation.")
###############################################################################
def git_clone():
    os.makedirs(base_dir)
    print ("Cloning {} into {}".format(git_repo, base_dir))
    subprocess.call(cmd_git_clone.format(git_repo, base_dir), shell=True)
    os.chdir(base_dir)
def git_pull():
    os.chdir(base_dir)
    print ("Pulling latest changes from {}".format(git_repo))
    subprocess.call(cmd_git_pull, shell=True)
###############################################################################
# main                                                                        #
###############################################################################
#base_dir = tempfile.mkdtemp()
if os.path.exists(base_dir):
    git_pull()
else:
    git_clone()
print ("Changing to remotes/origin/{} branch".format(git_branch))
subprocess.call(cmd_git_ckout.format("remotes/origin/" + git_branch), shell=True)
print ("Creating git snapshot")
create_git_snap(base_dir)
os.chdir(base_dir)
print ("Checking out from VSS")
code = subprocess.call(cmd_vss_ckout.format(vss_proj), stdout=subprocess.DEVNULL, shell=True)
if code == err_vss:
    error_ckout()
    sys.exit()
print ("Checking in to VSS")
subprocess.call(cmd_vss_ckin.format(vss_proj), shell=True)
print ("Synchronising added/removed files in git with VSS")
sync_git_vss(vss_proj, base_dir)
# create git tag
if use_git_tag == True:
    os.chdir(base_dir)
    print ("Creating git tag {}".format(git_tag))
    subprocess.call(cmd_git_tag.format(git_tag), shell=True)
    print ("Pushing git tag")
    subprocess.call(cmd_git_push, shell=True)
    os.chdir("..")
# resetting to master branch
os.chdir(base_dir)
subprocess.call(cmd_git_ckout.format("master"), shell=True)
print ("Done!")
