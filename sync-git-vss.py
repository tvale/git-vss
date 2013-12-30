###############################################################################
# synchronise a vss database with a git branch                                #
###############################################################################
# assumptions:                                                                #
#   both {ss,git}.exe are in PATH;                                            #
#   %SSPATH% exists and contains the VSS database location;                   #
#   commands used to collect git snapshot produce a directory listing with    #
#   one file/sub-directory per line;                                          #
#   the VSS user of this script does not have the VSS project checked out     #
#   externally (used in error_ckout.)                                         #
#                                                                             #
# parameters:                                                                 #
#    #1  git repository;                                                      #
#    #2  git user;                                                            #
#    #3  git user password;                                                   #
#    #4  git branch;                                                          #
#    #5  vss repository;                                                      #
#    #6  vss user;                                                            #
#    #7  vss user password;                                                   #
#   [#8] optional git tag.                                                    #
#                                                                             #
# to do:                                                                      #
#   git auth? apparently no way to do so programmatically--use ssh;           #
#   git tag at the end;                                                       #
#   failure handling?                                                         #
#                                                                             #
# high-level description:                                                     #
#   1. clone the git branch to a temporary directory;                         #
#   2. take a snapshot Sgit of the directory structure;                       #
#   3. checkin modified files to vss:                                         #
#       3.1. checkout the vss repository without overwritting local files;    #
#       3.2. checkin the vss repository;                                      #
#   4. take a snapshot Svss of the directory structure;                       #
#   5. add/delete in vss files added/removed in git:                          #
#       5.1. from Sgit obtain the set of files Fgit;                          #
#       5.2. from Svss obtain the set of files Fvss;                          #
#       5.3. delete from vss each f in Fvss and not in Fgit;                  #
#       5.4. add to vss each f in Fgit and not in Fvss;                       #
#   6. add/delete in vss sub-directories added/removed in git:                #
#       6.1. from Sgit obtain the set of sub-directories Dgit;                #
#       6.2. from Svss obtain the set of sub-directories Dvss;                #
#       6.3. delete from vss each d in Dvss and not in Dgit;                  #
#       6.4. add to vss each d in Dgit and not in Dvss;                       #
#       6.5. apply steps 4-6 to each d in Dgit and Dvss;                      #
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
# log filename                                                                #
###############################################################################
log_fn = "sync_git_vss.log"
###############################################################################
# cli arguments                                                               #
###############################################################################
use_git_tag = False
git_repo    = sys.argv[1] 
git_user    = sys.argv[2]
git_passwd  = sys.argv[3]
git_branch  = sys.argv[4]
vss_repo    = sys.argv[5]
vss_user    = sys.argv[6]
vss_passwd  = sys.argv[7]
if len(sys.argv) == 9:
    use_git_tag = True
    git_tag     = sys.argv[8]
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
# windows-specific shell commands                                             #
###############################################################################
cmd_win_dir_files = "dir /A:-D /B"
cmd_win_dir_dirs  = "dir /A:D /B"
###############################################################################
# git command templates                                                       #
###############################################################################
cmd_git_clone = "git clone {} --branch {} --single-branch {}"
###############################################################################
# vss command templates                                                       #
###############################################################################
cmd_vss_cp        = "ss cp {}"
cmd_vss_dir       = "ss dir -F"
cmd_vss_get       = "ss get {}"
cmd_vss_add       = "ss add {} -R -C- -I-"
cmd_vss_del       = "ss delete {} -I-Y"
cmd_vss_ckin      = "ss checkin {} -R -C-"
cmd_vss_ckout     = "ss checkout {} -R -G-"
cmd_vss_undockout = "ss undocheckout {} -R -G-"
###############################################################################
# vss error return codes                                                      #
###############################################################################
err_vss = 100
ok_vss  = 0
###############################################################################
# helper functions---git snapshot                                             #
###############################################################################
def parse_files_cwd(files, fn):
    with open(fn, "rU") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                files.append(stripped)
def parse_subdirs_cwd(subdirs, fn):
    with open(fn, "rU") as f:
        for line in f:
            stripped = line.strip()
            if stripped and stripped != ".git":
                subdirs.append(stripped)
def parse_cwd(sh_cmd, parse_fun):
    result = []
    # redirect list output to a temporary file, parse names into list and
    # remove temporary file
    fd, fn = tempfile.mkstemp()
    try:
        subprocess.check_call(sh_cmd, stdout=fd, stderr=log, shell=True)
        os.close(fd)
        parse_fun(result, fn)
    except subprocess.CalledProcessError:
        os.close(fd)
    os.remove(fn)
    return result
def create_git_snap(dir):
    os.chdir(dir)
    #print (os.getcwd())
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
    subprocess.call(cmd_vss_dir, stdout=fd, stderr=log, shell=True)
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
    #print (files_to_add)
    for f in files_to_add:
        code = subprocess.call(cmd_vss_add.format(f), stdout=log, stderr=log, shell=True)
        if code == err_vss:
            # what if 'f' is checked out?
            subprocess.call(cmd_vss_ckout.format(f), stdout=log, stderr=log, shell=True)
            subprocess.call(cmd_vss_ckin.format(f), stdout=log, stderr=log, shell=True)
    #print (files_to_rem)
    for f in files_to_rem:
        subprocess.call(cmd_vss_del.format(f), stdout=log, stderr=log, shell=True)
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
    #print (dirs_to_add)
    for d in dirs_to_add:
        subprocess.call(cmd_vss_add.format(d), stdout=log, stderr=log, shell=True)
    #print (dirs_to_rem)
    for d in dirs_to_rem:
        # we apply recursively because deleting a directory with files prompts
        # user input from vss regarding checkout operations from different
        # sources
        sync_git_vss(d, d)
        subprocess.call(cmd_vss_undockout.format(d), stdout=log, stderr=log, shell=True)
        subprocess.call(cmd_vss_del.format(d), stdout=log, stderr=log, shell=True)
    return dirs_to_rec
def sync_git_vss(vss_repo, dir):
    # set vss repository and change cwd to 'dir'
    subprocess.call(cmd_vss_cp.format(vss_repo), stdout=log, stderr=log, shell=True)
    os.chdir(dir)
    #print (os.getcwd())
    vss_files, vss_dirs = create_vss_snap_cwd()
    sync_files(vss_files)
    git_vss_dirs = sync_dirs(vss_dirs)
    #print (dirs_to_rec)
    for d in git_vss_dirs:
        sync_git_vss(d, d)
    subprocess.call(cmd_vss_cp.format(".."), stdout=log, stderr=log, shell=True)
    os.chdir("..")
###############################################################################
# helper functions---rollback on error                                        #
###############################################################################
def error_ckout():
    print ("Error while checking out from VSS")
    # answer yes to undo the check out of files that have been modified/removed
    # in git
    cmd = cmd_vss_undockout + " " + "-I-Y"
    subprocess.call(cmd.format(vss_repo), stdout=log, stderr=log, shell=True)
def print_log_info():
    print ("View {} for details".format(log_fn))
###############################################################################
# main                                                                        #
###############################################################################
log = open(log_fn, "a+")
log.write(time.strftime("%c"))
log.write("\n")
base_dir = tempfile.mkdtemp()
print ("Cloning {} into {}".format(git_repo, base_dir))
subprocess.call(cmd_git_clone.format(git_repo, git_branch, base_dir), stdout=log, stderr=log, shell=True)
print ("Creating git snapshot")
create_git_snap(base_dir)
os.chdir(base_dir)
print ("Checking out from VSS")
code = subprocess.call(cmd_vss_ckout.format(vss_repo), stdout=log, stderr=log, shell=True)
if code == err_vss:
    error_ckout()
    print_log_info()
    sys.exit()
print ("Checking in to VSS")
subprocess.call(cmd_vss_ckin.format(vss_repo), stdout=log, stderr=log, shell=True)
print ("Synchronising added/removed files in git with VSS")
sync_git_vss(vss_repo, base_dir)
print_log_info()
# remove temporary base directory
#shutil.rmtree(base_dir, True)
log.write("\n")
log.close()    
