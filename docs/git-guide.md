# git for the team

Repo: https://github.com/RomeoCoding/dryflash
Rule: never work on `main` directly. Every change goes on your own branch, then a pull request.

## first time only

```sh
git clone https://github.com/RomeoCoding/dryflash.git
cd dryflash
git config user.name "Your Name"
git config user.email "you@example.com"
```

Ask me to add you as a collaborator first, or the push will be rejected.

## start something new

```sh
git checkout main
git pull
git checkout -b yourname/what-you-do
```

Name it like `romeo/sensor-fix` or `dana/readme`. One branch per task.

## save your work

```sh
git status                 # what changed
git add path/to/file       # or: git add .   (check git status first)
git commit -m "Fix ADC byte order in the voltmeter example"
```

Commit often. Message = what changed, in one line.

## send it to GitHub

```sh
git push -u origin yourname/what-you-do    # first push of the branch
git push                                   # every push after that
```

Then open GitHub, you'll see "Compare & pull request". Open the PR into `main`, write two lines on
what it does, tag me. Don't merge your own PR.

## get the latest from main

Someone merged stuff and you want it in your branch:

```sh
git checkout main
git pull
git checkout yourname/what-you-do
git merge main
```

## conflicts

If `git merge main` says CONFLICT:

1. open the files it lists, look for `<<<<<<<`, `=======`, `>>>>>>>`
2. keep the right code, delete the markers
3. `git add <file>` then `git commit`

Not sure which side is right? Stop and ask, don't guess.

## oops

| problem | fix |
|---|---|
| changed a file, want it back | `git restore path/to/file` |
| committed to `main` by mistake (not pushed) | `git branch yourname/fix` then `git reset --hard origin/main`, then `git checkout yourname/fix` |
| wrong commit message (not pushed) | `git commit --amend -m "new message"` |
| don't know what state you're in | `git status` and `git log --oneline -5`, send me the output |

## don'ts

- no `git push --force` on anything shared
- no committing secrets, `.env`, build folders or big binaries
- no pushing to `main`
