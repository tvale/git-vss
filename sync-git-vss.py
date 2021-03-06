﻿# -*- coding: utf-8 -*-
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
cmd_win_dir_files = 'dir /A:-D /B'
cmd_win_dir_dirs  = 'dir /A:D /B'
cmd_win_del_dir   = 'rm -rf "{}"'
cmd_win_git_hash  = 'echo {} >"{}"'
cmd_win_del_file  = 'rm -f "{}"'
###############################################################################
# git command templates                                                       #
###############################################################################
cmd_git_clone = 'git clone {} {}'
cmd_git_ckout = 'git checkout {}'
cmd_git_fetch = 'git fetch origin'
cmd_git_tag   = 'git tag {}'
cmd_git_push  = 'git push --tags origin'
cmd_git_hash  = 'git --no-pager log --format=format:%H -1'
cmd_git_log   = 'git --no-pager log --oneline --name-only --format=format: {}'
###############################################################################
# vss command templates                                                       #
###############################################################################
cmd_vss_cd        = 'ss cd "{}"'
cmd_vss_create    = 'ss create "{}" -I-'
cmd_vss_add       = 'ss add "{}" -I-'
cmd_vss_cp        = 'ss cp "{}"'
cmd_vss_dir       = 'ss dir'
cmd_vss_get       = 'ss get "{}"'
cmd_vss_del       = 'ss delete "{}" -I-Y'
cmd_vss_ckin      = 'ss checkin "{}" -I-'
cmd_vss_ckout     = 'ss checkout "{}" -G- -I-'
cmd_vss_undockout = 'ss undocheckout "{}" -R -G- -I-Y'
cmd_vss_rename    = 'ss rename "{}" "{}"'
cmd_vss_proj      = 'ss project'
cmd_vss_git_ckout = 'ss checkout "{}"'
cmd_vss_git_ckin  = 'ss checkin "{}" -I-'
###############################################################################
# vss error return codes                                                      #
###############################################################################
err_vss = 100
ok_vss  = 0
pathlen_vss = 259
###############################################################################
# timestamp size for rename                                                   #
###############################################################################
ts_size = 10
gitcommit_file = ".gitcommit"
vss_encoding = "cp860"
git_encoding = "utf8"
cmd_encoding = "65001"
###############################################################################
# helper functions---fatal error                                              #
###############################################################################
def fatal_error(msg, subproj, filename):
    subprocess.call(cmd_vss_proj)
    print (os.getcwd())
    subprocess.call(cmd_vss_undockout.format(vss_proj), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.chdir(base_dir)
    try:
        os.remove(gitcommit_file)
    except FileNotFoundError:
        pass # whatever
    print ("Error on " + subproj + "/" + filename + ": " + msg)
    sys.exit(1)
def warn(msg, subproj):
    print ("Warning on " + subproj + ": " + msg)
###############################################################################
# helper functions---path length                                              #
###############################################################################
def trunc_filename(subproj, filename):
    path = subproj + "/" + filename
    trunc = len(path) + ts_size - pathlen_vss
    index = len(filename) - trunc
    if index < 0:
        fatal_error("Cannot rename " + path + " without violating VSS path length restrictions.")
    else:
        return filename[:index]
###############################################################################
# helper functions---vss                                                      #
###############################################################################
def vss_get_proj():
    p = subprocess.Popen(cmd_vss_proj.split(), stdout=subprocess.PIPE)
    out, err = p.communicate()
    proj = out.decode(git_encoding).strip()[19:].replace("\r", "").replace("\n", "")
    return proj
def vss_get_error(e):
    return e.output.decode(vss_encoding).strip()
def vss_cd_root():
    try:
        subprocess.check_output(cmd_vss_cd.format(vss_proj), stderr=subprocess.STDOUT)
        os.chdir(base_dir)
    except subprocess.CalledProcessError as e:
        err = vss_get_error(e)
        if "does not exist" in err:
            try:
                subprocess.check_output(cmd_vss_create.format(vss_proj), stderr=subprocess.STDOUT)
                subprocess.check_output(cmd_vss_cd.format(vss_proj), stderr=subprocess.STDOUT)
                os.chdir(base_dir)
            except subprocess.CalledProcessError as e:
                err = vss_get_error(e)
                fatal_error(err, vss_proj, "")
        else:
            fatal_error(err, vss_proj, "")
def vss_git_hash_set(commit):
    subprocess.call(cmd_win_git_hash.format(commit, gitcommit_file), shell=True)
    try:
        subprocess.check_output(cmd_vss_git_ckin.format(gitcommit_file), stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        err = vss_get_error(e)
        if "not an existing" in err:
            try:
                subprocess.check_output(cmd_vss_add.format(gitcommit_file), stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                err = vss_get_error(e)
                fatal_error(e)
        else:
            fatal_error(err, subproj, filename)
def vss_git_hash_get():
    try:
        subprocess.check_output(cmd_vss_git_ckout.format(gitcommit_file), stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        err = vss_get_error(e)
        if "not an existing filename" in err: # no sync file
            return None
        elif "You currently have" not in err: 
            fatal_error(err, "", "")
    p = subprocess.Popen(["cat", gitcommit_file], stdout=subprocess.PIPE)
    out, err = p.communicate()
    return out.decode(git_encoding)
def vss_create_cd(path):
    try:
        subprocess.check_output(cmd_vss_create.format(path), stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        err = vss_get_error(e)
        if err.endswith("already exists") == False:
            fatal_error(err, subproj, filename)
    subprocess.call(cmd_vss_cd.format(path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.chdir(path)
def vss_create_subproj(path, dirs=[]):
    dirname = os.path.dirname(path)
    dirs.insert(0, os.path.basename(path))
    try:
        if dirname != "":
            subprocess.check_output(cmd_vss_cd.format(dirname), stderr=subprocess.STDOUT)
            os.chdir(dirname)
        for dir in dirs:
            vss_create_cd(dir)
    except subprocess.CalledProcessError:
        vss_create_subproj(dirname, dirs)
def vss_rename_cd(subproj):
    try:
        subprocess.check_output(cmd_vss_rename.format(subproj, subproj), stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        err = vss_get_error(e)
        if "that name already exists" not in err:
            raise e
    subprocess.check_output(cmd_vss_cd.format(subproj), stderr=subprocess.STDOUT)
def vss_cd_create(subproj):
    if subproj == "":
        return
    try: # try to change to subproject
        for dir in subproj.split("/"):
            vss_rename_cd(dir)
        os.chdir(subproj)
    except subprocess.CalledProcessError as e:
        err = vss_get_error(e)
        if err.endswith("not exist") == True: # subproject doesn't exist yet
            vss_cd_root()
            vss_create_subproj(subproj, [])
        else:
            fatal_error(err, subproj, filename)
def vss_add_or_modify(subproj, filename):
    path = subproj + "/" + filename
    vss_cd_create(subproj)
    try: # add
        subprocess.check_output(cmd_vss_add.format(filename), stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        err = vss_get_error(e)
        if err.endswith("already exists"): # file already exists
            try: # checkout
                subprocess.check_output(cmd_vss_ckout.format(filename), stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e:
                err = vss_get_error(e)
                if "You currently have" in err: # already checked out by me, checkin
                    try:
                        subprocess.check_output(cmd_vss_ckin.format(filename), stderr=subprocess.STDOUT)
                    except subprocess.CalledProcessError as e: # could not checkin, something went wrong
                        err = vss_get_error(e)
                        fatal_error(err, subproj, filename)
                else: # could not checkout, something went wrong
                    fatal_error(err, subproj, filename)
            try: # file checked out, checkin
                subprocess.check_output(cmd_vss_ckin.format(filename), stderr=subprocess.STDOUT)
            except subprocess.CalledProcessError as e: # could not checkin, something went wrong
                err = vss_get_error(e)
                fatal_error(err, subproj, filename)
        else: # file does not exist but add failed, something went wrong
            fatal_error(err, subproj, filename)
        try: # rename
            subprocess.check_output(cmd_vss_rename.format(filename, filename), stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            err = vss_get_error(e)
            if "that name already exists" not in err:
                fatal_error(err)
def vss_delete_empty_subproj(subproj):
    if subproj == "":
        return
    # get output of ss dir
    p = subprocess.Popen(cmd_vss_dir.split(), stdout=subprocess.PIPE)
    out, err = p.communicate()
    vss_dir_empty = "No items found" in out.decode(vss_encoding).strip()
    if vss_dir_empty:
        # rename and delete subproject
        # change to vss subproject 'vss_proj'/'path'
        path = os.path.dirname(subproj)
        filename = os.path.basename(subproj)
        try: # rename
            ts = str(time.time())[:ts_size]
            new_filename = trunc_filename(path, filename) + ts
            old_path = vss_proj + "/" + path + "/" + filename
            renamed_path = vss_proj + "/" + path + "/" + new_filename
            subprocess.check_output(cmd_vss_rename.format(old_path, renamed_path), stderr=subprocess.STDOUT)
            subprocess.check_output(cmd_vss_del.format(renamed_path), stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e: # could not rename, something went wrong
            err = vss_get_error(e)
            fatal_error(err, subproj, filename)
        try:
            subprocess.check_output(cmd_vss_cp.format(vss_proj + "/" + path), stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError as e:
            err = vss_get_error(e)
            fatal_error(err, subproj, "")
        vss_delete_empty_subproj(path)
def vss_delete(subproj, filename):
    path = subproj + "/" + filename
    try: # change vss project
        subprocess.check_output(cmd_vss_cd.format(subproj), stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e: # if changing project fails, nothing to do---project does not exist?
        return
    try: # checkout
        subprocess.check_output(cmd_vss_ckout.format(filename), stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        err = vss_get_error(e)
        if "not an existing" in err or "has been deleted" in err: # file doesn't exist, nothing to do
            return
        elif "You currently have" not in err: # unless we already have the file checked out, something went wrong
            fatal_error(err, subproj, filename)
    try: # rename
        ts = str(time.time())[:ts_size]
        new_filename = trunc_filename(subproj, filename) + ts
        subprocess.check_output(cmd_vss_rename.format(filename, new_filename), stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e: # could not rename, something went wrong
        err = vss_get_error(e)
        fatal_error(err, subproj, filename)
    try: # delete rename file
        subprocess.check_output(cmd_vss_del.format(new_filename), stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        err = vss_get_error(e)
        if "has been deleted" not in err: # unless the file has already been deleted, something went wrong
            fatal_error(err, subproj, filename)
    dir_exists_in_git = os.path.isdir(subproj)
    if not dir_exists_in_git:
        vss_delete_empty_subproj(subproj)
###############################################################################
# helper functions---git                                                      #
###############################################################################
def git_hash():
    p = subprocess.Popen(cmd_git_hash.split(), stdout=subprocess.PIPE)
    out, err = p.communicate()
    return out.decode(git_encoding) # hash
def git_changes(since=None):
    if since is not None:
        commit_range = "HEAD..." + since
    else:
        commit_range = ""
    proc = subprocess.Popen(cmd_git_log.format(commit_range).split(), stdout=subprocess.PIPE)
    out, err = proc.communicate()
    changes = out.decode(git_encoding).splitlines()
    def not_empty(str):
        return str != ""
    changes = [line for line in changes if not_empty(line)]
    s = set()
    def unique(str, seen):
        if str.lower() in seen:
            return False
        else:
            seen.add(str.lower())
            return True
    changes = [path for path in changes if unique(path, s)]
    return changes # list of paths
def git_clone():
    os.makedirs(base_dir)
    print ("Cloning {} into {}".format(git_repo, base_dir))
    subprocess.call(cmd_git_clone.format(git_repo, base_dir))
def git_fetch():
    os.chdir(base_dir)
    print ("Fetching latest changes from {}".format(git_repo))
    subprocess.call(cmd_git_fetch)
###############################################################################
# helper functions---sync                                                     #
###############################################################################
def process_change(path, i, t):
    vss_cd_root()
    subproj = os.path.dirname(path)
    filename = os.path.basename(path)
    file_exists_in_git = os.path.isfile(path)
    if file_exists_in_git:
        print (str(i) + "/" + str(t) + " Adding/modifying " + path)
        vss_add_or_modify(subproj, filename)
    else:
        print (str(i) + "/" + str(t) + " Deleting " + path)
        vss_delete(subproj, filename)
        dir_exists_in_git = os.path.isdir(subproj)
def process_changes(changes):
    i = 1
    t = len(changes)
    for change in changes:
        process_change(change, i, t)
        i = i + 1
    print ("All changes processed")
###############################################################################
# main                                                                        #
###############################################################################
# setup windows cmd code point (fixes encoding errors)
subprocess.call("chcp {}".format(cmd_encoding), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)
# setup git repository
if os.path.exists(base_dir):
    git_fetch()
else:
    git_clone()
os.chdir(base_dir)
print ("Changing to remotes/origin/{} branch".format(git_branch))
subprocess.call(cmd_git_ckout.format("remotes/origin/" + git_branch), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
vss_cd_root()
# get changes since last sync commit hash
sync_commit = vss_git_hash_get()
hash = git_hash()
if sync_commit is None:
    print ("Replaying from first git commit until " + hash[:7] + " (.gitcommit not found)")
else:
    print ("Replaying from " + sync_commit[:7] + " until " + hash[:7])
changes = git_changes(sync_commit)
# sync
process_changes(changes)
vss_cd_root()
# update last sync commit hash
vss_git_hash_set(git_hash())
# create git tag
if use_git_tag == True:
    print ("Creating git tag {}".format(git_tag))
    subprocess.call(cmd_git_tag.format(git_tag))
    print ("Pushing git tag")
    subprocess.call(cmd_git_push)
print ("Done!")
