git-vss
=======
A Python sript to synchronise a VSS project with a git branch.
Makes use of Windows-specific commands.

#### Assumptions
* Both {ss,git}.exe are in **%PATH%**;
* **%SSPATH%** exists and contains the VSS database location---where `srcsafe.ini` is;
* Commands used to collect git snapshot produce a directory listing with one
file/sub-directory per line;
* The VSS user of this script does not have the VSS project checked out
externally (used in `error_ckout`).

#### Parameters
1. git URL with user and password, e.g., https://user:passwd@bitbucket.org/owner/repo.git;
2. git branch;
3. VSS project;
4. VSS user;
5. VSS user password;
6. [Optional git tag.]

#### Example usage
```
python sync-git-vss.py https://palves:passwd@bitbucket.org/owner/repo.git master $/Project palves passwd [1.0]
```

#### High-level description
1. Clone the git branch to a temporary directory;
2. Take a snapshot Sgit of the directory structure;
3. Checkin modified files to VSS:
  1. Checkout the VSS project without overwritting local files;
  2. Checkin the VSS project;
4. Take a snapshot Svss of the directory structure;
5. Add/delete in VSS files added/removed in git:
  1. From Sgit obtain the set of files Fgit;
  2. From Svss obtain the set of files Fvss;
  3. Delete from VSS each f in Fvss and not in Fgit;
  4. Add to VSS each f in Fgit and not in Fvss;
6. Add/delete in VSS sub-directories added/removed in git:
  1. From Sgit obtain the set of sub-directories Dgit;
  2. From Svss obtain the set of sub-directories Dvss;
  3. Delete from VSS each d in Dvss and not in Dgit;
  4. Add to VSS each d in Dgit and not in Dvss;
  5. Apply steps 4-6 to each d in Dgit and Dvss;

