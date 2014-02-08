git-vss
=======

synchronise a vss project with a git branch.

###### assumptions
* Both {ss,git}.exe are in **PATH**;
* **%SSPATH%** exists and contains the VSS database location---where `srcsafe.ini` is;
* Commands used to collect git snapshot produce a directory listing with one
file/sub-directory per line;
* The VSS user of this script does not have the VSS project checked out
externally (used in `error_ckout`.)

###### parameters
1. git url with user and password, e.g., https://user:passwd@bitbucket.org/owner/repo.git;
2. git branch;
3. vss project;
4. vss user;
5. vss user password;
6. optional git tag.

###### example
```
python sync-git-vss.py https://palves:passwd@bitbucket.org/owner/repo.git master $/Project palves passwd [1.0]
```

###### high-level description
1. clone the git branch to a temporary directory;
2. take a snapshot Sgit of the directory structure;
3. checkin modified files to vss:
  1. checkout the vss project without overwritting local files;
  2. checkin the vss project;
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
