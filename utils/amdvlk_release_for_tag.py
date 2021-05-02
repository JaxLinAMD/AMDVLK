#!/usr/bin/python3

# This script is used to build the AMD open source vulkan driver and make a deb package from github for tags.

# Before running this script, please install dependency packages with
# pip3 install gitpython
# pip3 install PyGithub

import sys
import os
import string
import time
import datetime
import git
import shutil
import re
from optparse import OptionParser
from github import Github

class Worker:
    def __init__(self):
        self.workDir      = os.getcwd()
        self.srcDir       = self.workDir + '/amdvlk_src/'
        self.pkgDir       = self.workDir + '/amdvlk_pkg/'
        self.buildDir     = ''
        self.pkgSharedDir = os.path.join(self.workDir, 'pkgShared')
        self.branch       = 'master'
        self.components   = ['xgl', 'pal', 'llpc', 'spvgen', 'llvm-project', 'MetroHash', 'CWPack']
        self.latestTag    = []
        self.releasedTags = [] # The tags already released on github
        self.commits      = {'xgl':'', 'pal':'', 'llpc':'', 'spvgen':'', 'llvm-project':'', 'MetroHash':'', 'CWPack':''}
        self.descript     = ''
        self.targetRepo   = 'https://github.com/GPUOpen-Drivers/'
        self.choice       = 'build'
        self.distro       = self.DistributionType()

    def GetOpt(self):
        parser = OptionParser()

        parser.add_option("-w", "--workDir", action="store",
                          type="string",
                          dest="workDir",
                          help="Specify the location of source code, or download it from github")

        parser.add_option("-a", "--accessToken", action="store",
                          type="string",
                          dest="accessToken",
                          help="Specify the accessToken to access github")

        parser.add_option("-t", "--targetRepo", action="store",
                          type="string",
                          dest="targetRepo",
                          help="Specify the target repo of github, default is " + self.targetRepo)

        parser.add_option("-c", "--choice", action="store",
                          type="string",
                          dest="choice",
                          help="Build package or release it? Default is: " + self.choice)

        (options, args) = parser.parse_args()

        if options.workDir:
            print("The source code is under %s" % (options.workDir))
            self.workDir = options.workDir
            self.srcDir  = self.workDir + "/amdvlk_src/"
            self.pkgDir  = self.workDir + "/amdvlk_pkg/"
        else:
            print("The source code is not specified, downloading from github to: " + self.workDir)

        if not os.path.exists(self.srcDir):
            os.makedirs(self.srcDir)

        if options.accessToken:
            self.accessToken = options.accessToken
        else:
            print("Please specify the access token to github, exiting...")
            sys.exit(-1)

        if options.targetRepo:
            self.targetRepo = options.targetRepo

        print("The target repo is " + self.targetRepo)

        if options.choice:
            self.choice = options.choice
        else:
            print('Please specify choice, build or release?')
            sys.exit(-1)

    def ConnectGithub(self):
        foundRepo = False
        self.github = Github(self.accessToken)
        for repo in self.github.get_user().get_repos():
            if (repo.name == 'AMDVLK'):
                self.repo = repo
                foundRepo = True

        if (foundRepo == False):
            print("Fatal: AMDVLK repo is not found")
            sys.exit(-1)

    def DistributionType(self):
        result = os.popen('lsb_release -is').read().strip()
        if (result == 'Ubuntu'):
            return result
        elif (result == 'RedHatEnterprise' or result == 'RedHatEnterpriseWorkstation'):
            return 'RHEL'
        else:
            print('Unknown Linux distribution: ' + result)
            sys.exit(-1)

    def GetReleasedTagsOnGithub(self):
        releases = self.repo.get_releases()

        for release in releases:
            self.releasedTags.append(release.tag_name)

    def CloneAMDVLK(self):
        # Clone the AMDVLK and get the latest tag
        os.chdir(self.srcDir)
        # Remove it if it exists
        if os.path.exists(self.srcDir + 'AMDVLK'):
            shutil.rmtree(self.srcDir + 'AMDVLK')

        git.Git().clone(self.targetRepo + 'AMDVLK')
        repo = git.Repo('AMDVLK')
        tags = repo.git.tag()
        self.latestTag = tags.split('\n')[-1]

    def CloneAMDVLKComponents(self):
        os.chdir(self.srcDir)

        for i in self.components:
            if not os.path.exists(self.srcDir + i):
                print("Cloning " + i + ".....")
                git.Git().clone(self.targetRepo + i)

            repo = git.Repo(i)
            repo.git.clean('-xdf')
            if (i == 'llvm-project'):
                repo.git.checkout('remotes/origin/amd-gfx-gpuopen-' + self.branch, B='amd-gfx-gpuopen-' + self.branch)
            elif (i == 'MetroHash' or i == 'CWPack'):
                repo.git.checkout('remotes/origin/amd-master', B='amd-master')
            else:
                repo.git.checkout('remotes/origin/' + self.branch, B=self.branch)
            repo.git.pull()

    def CheckoutTag(self, tag):
        os.chdir(self.srcDir)
        repo = git.Repo('AMDVLK')
        repo.git.checkout(tag)
        self.descript = repo.head.commit.message
        self.version = tag[2:]

        # Get the commits from default.xml
        with open('AMDVLK/default.xml', 'r') as manifest:
            lines       = manifest.readlines()
            for line in lines:
                for i in self.commits:
                    index = line.find("revision=");
                    if (index > -1) and (line.find(i) > -1):
                        startIndex      = index + len("revision=\"")
                        stopIndex       = line.find("\"", startIndex)
                        self.commits[i] = line[startIndex:stopIndex]
                        break

        # Checkout commits
        for i in self.commits:
            print('Checking out ' + i + ': ' + self.commits[i])
            repo = git.Repo(i)
            repo.git.clean('-xdff')
            repo.git.checkout(self.commits[i])

    def Build(self):
        self.PreparePkgSharedResources()

        if self.distro == 'Ubuntu':
            self.MakeDriverPackage('64')
            self.ArchiveAmdllpcTools('amd64')
            self.MakeDriverPackage('32')
            self.ArchiveAmdllpcTools('i386')
        elif self.distro == 'RHEL':
            self.MakeDriverPackage('64')

    def MakeDriverPackage(self, arch):
        cmakeName = 'cmake '
        if (self.distro == 'RHEL'):
            cmakeName = 'source scl_source enable devtoolset-7 && cmake '

        # Fetch spvgen resources
        os.chdir(self.srcDir + 'spvgen/external')
        if os.system('python fetch_external_sources.py'):
            print('SPVGEN: fetch external sources failed')
            exit(-1)

        # Make driver package
        self.buildDir   = 'xgl/Release64' if arch == '64' else 'xgl/Release32'
        cmakeFlags = ' -G Ninja -S xgl -B ' + self.buildDir + ' -DBUILD_WAYLAND_SUPPORT=ON -DPACKAGE_VERSION=' + self.version
        cFlags     = '' if arch == '64' else ' -DCMAKE_C_FLAGS=\"-m32 -march=i686\" -DCMAKE_CXX_FLAGS=\"-m32 -march=i686\"'

        os.chdir(self.srcDir)
        if os.path.exists(self.buildDir):
            shutil.rmtree(self.buildDir)
        os.makedirs(self.buildDir)

        if os.system(cmakeName + cmakeFlags + cFlags):
            print(cmakeName + cmakeFlags + cFlags + ' failed')
            exit(-1)

        # Build driver
        if os.system('cmake --build ' + self.buildDir):
            print('build amdvlk failed')
            exit(-1);

        # Make driver package
        if os.system('cmake --build ' + self.buildDir + ' --target makePackage'):
            print('make driver package failed')

        # Build spvgen
        if os.system('cmake --build ' + self.buildDir + ' --target spvgen'):
            print('SPVGEN: build failed')
            exit(-1);

        # Build amdllpc
        if os.system('cmake --build ' + self.buildDir + ' --target amdllpc'):
            print('build amdllpc failed')
            exit(-1);

        # Copy driver package to workDir, will be uploaded to github
        os.system('cp ' + self.buildDir + '/*.rpm ' + self.workDir)
        os.system('cp ' + self.buildDir + '/*.deb ' + self.workDir)

    def PreparePkgSharedResources(self):
        if os.path.exists(self.pkgSharedDir):
            shutil.rmtree(self.pkgSharedDir)
        os.makedirs(self.pkgSharedDir)
        os.chdir(self.pkgSharedDir)

        with open('changelog', 'w') as changelog:
            changelog.write(self.descript + '\n')
            changelog.write('For more detailed information, pelase check ' + self.targetRepo + 'AMDVLK/releases/tag/' + self.latestTag)

        shutil.copy('changelog', 'changelog.Debian')
        os.system('gzip -9 changelog.Debian')
        shutil.copy('changelog.Debian.gz', self.srcDir + 'xgl/changelog.Debian.gz')

    def ArchiveAmdllpcTools(self, arch):
        toolsDir = 'amdllpc_' + arch

        os.chdir(self.workDir)
        if os.path.exists(toolsDir):
            shutil.rmtree(toolsDir)
        os.makedirs(toolsDir)

        os.system('cp ' + os.path.join(self.srcDir, self.buildDir + '/spvgen/spvgen.so') + ' ' + toolsDir)
        os.system('cp ' + os.path.join(self.srcDir, self.buildDir + '/compiler/llpc/amdllpc') + ' ' + toolsDir)
        os.system('zip -r ' + toolsDir + '.zip ' + toolsDir)

    def Package(self):
        self.PreparePkgSharedResources()

        if (self.distro == 'Ubuntu'):
            self.MakeDebPackage('amd64')
            self.ArchiveAmdllpcTools('amd64')
            self.MakeDebPackage('i386')
            self.ArchiveAmdllpcTools('i386')
        elif (self.distro == 'RHEL'):
            self.MakeRpmPackage()

    def Release(self, tag):
        os.chdir(self.workDir)

        rpmPackageName = 'amdvlk-' + self.version + '.x86_64.rpm'
        debPackage64bitName = 'amdvlk_' + self.version + '_amd64.deb'
        debPackage32bitName = 'amdvlk_' + self.version + '_i386.deb'
        amdllpc64bitName = 'amdllpc_amd64.zip'
        amdllpc32bitName = 'amdllpc_i386.zip'

        if not os.path.isfile(rpmPackageName):
            print('Can not find package: ' + rpmPackageName)
            sys.exit(-1)
        if not os.path.isfile(debPackage64bitName):
            print('Can not find package: ' + debPackage64bitName)
            sys.exit(-1)
        if not os.path.isfile(debPackage32bitName):
            print('Can not find package: ' + debPackage32bitName)
            sys.exit(-1)
        if not os.path.isfile(amdllpc64bitName):
            print('Can not find package: ' + amdllpc64bitName)
            sys.exit(-1)
        if not os.path.isfile(amdllpc32bitName):
            print('Can not find package: ' + amdllpc32bitName)
            sys.exit(-1)


        releaseNote = '[Driver installation instruction](' + self.targetRepo + 'AMDVLK#install-with-pre-built-driver) \n\n'
        formated_str = self.descript.replace('New feature and improvement', '## New feature and improvement')
        formated_str = formated_str.replace('Issue fix', '## Issue fix')
        releaseNote += formated_str

        newRelease = self.repo.create_git_release(tag, tag, releaseNote, False, False)

        newRelease.upload_asset(rpmPackageName, rpmPackageName + '(RedHat 7.8 8.2)')
        newRelease.upload_asset(debPackage64bitName, debPackage64bitName + '(Ubuntu 18.04 20.04)')
        newRelease.upload_asset(debPackage32bitName, debPackage32bitName + '(Ubuntu 18.04 20.04)')
        newRelease.upload_asset(amdllpc64bitName, amdllpc64bitName)
        newRelease.upload_asset(amdllpc32bitName, amdllpc32bitName)

    def start(self):
        self.GetOpt()
        self.ConnectGithub()
        self.GetReleasedTagsOnGithub()
        self.CloneAMDVLK()
        # Build driver package for the latest tag.
        if self.latestTag not in self.releasedTags:
            print('Will create release for tag ' + self.latestTag)
            self.CloneAMDVLKComponents()
            self.CheckoutTag(self.latestTag)
            if (self.choice == 'build'):
                self.Build()
                print('The package is generated successfully for ' + self.latestTag)
            elif (self.choice == 'release'):
                self.Release(self.latestTag)
                print('Released ' + tag + ' successfully')
        else:
            print('Tag ' + self.latestTag + ' is already released, nothing to do.')

if __name__ == '__main__':
    worker = Worker()
    worker.start()

