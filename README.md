git-vss
=======

synchronise a vss database with a git branch.

###### assumptions
* Both {ss,git}.exe are in **PATH**;
* **%SSPATH%** exists and contains the VSS database location;
* Commands used to collect git snapshot produce a directory listing with one
file/sub-directory per line;
* The VSS user of this script does not have the VSS project checked out
externally (used in `error_ckout`.)

###### parameters
1. git repository;
2. git user;
3. git user password;
4. git branch;
5. vss repository;
6. vss user;
7. vss user password;
8. optional git tag.

###### high-level description
1. clone the git branch to a temporary directory;
2. take a snapshot Sgit of the directory structure;
3. checkin modified files to vss:
  1. checkout the vss repository without overwritting local files;
  2. checkin the vss repository;
4. take a snapshot Svss of the directory structure;
5. add/delete in vss files added/removed in git:
  1. from Sgit obtain the set of files Fgit;
  2. from Svss obtain the set of files Fvss;
  3. delete from vss each f in Fvss and not in Fgit;
  4. add to vss each f in Fgit and not in Fvss;
6. add/delete in vss sub-directories added/removed in git:
  1. from Sgit obtain the set of sub-directories Dgit;
  2. from Svss obtain the set of sub-directories Dvss;
  3. delete from vss each d in Dvss and not in Dgit;
  4. add to vss each d in Dgit and not in Dvss;
  5. apply steps 4-6 to each d in Dgit and Dvss;

###### (still) to do
* git authentication? apparently no way to do so programmatically--use ssh;
* git tag at the end;
* failure handling?
