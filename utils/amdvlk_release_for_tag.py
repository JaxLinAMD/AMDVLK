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

DriverVersionStub = 'DriverVersionStub'
ArchitectureStub  = 'ArchitectureStub'
Control = "Package: amdvlk\n\
Version: " + DriverVersionStub + "\n\
Architecture: " + ArchitectureStub + "\n\
Maintainer: Advanced Micro Devices (AMD) <gpudriverdevsupport@amd.com>\n\
Depends: libc6 (>= 2.17), libgcc1 (>= 1:3.4), libstdc++6 (>= 5.2)\n\
Conflicts: amdvlk\n\
Replaces: amdvlk\n\
Section: libs\n\
Priority: optional\n\
Multi-Arch: same\n\
Homepage: https://github.com/GPUOpen-Drivers/AMDVLK\n\
Description: AMD Open Source Driver for Vulkan"

SPEC = "Name: amdvlk\n\
Version: " + DriverVersionStub + "\n\
Release: el\n\
Summary: AMD Open Source Driver for Vulkan\n\
URL: https://github.com/GPUOpen-Drivers/AMDVLK\n\
License: MIT\n\
Group: System Environment/Libraries\n\
Vendor: Advanced Micro Devices (AMD) <gpudriverdevsupport@amd.com>\n\
Buildarch: x86_64\n\n\
%description\n\
%prep\n\
%build\n\
%pre\n\
%post\n\
%preun\n\
%postun\n\
%files\n\
/usr/lib64/amdvlk64.so\n\
/etc/vulkan/icd.d/amd_icd64.json\n\
/usr/share/doc/amdvlk/copyright\n\
/usr/share/doc/amdvlk/changelog\n\
%changelog"

class Worker:
    def __init__(self):
        self.binaryDir      = os.getcwd()
        self.pkgDir       = self.binaryDir + "/package/"
        self.pkgSharedDir = os.path.join(self.binaryDir, 'pkgShared')
        self.descript     = ""
        self.distro       = self.DistributionType()

    def GetOpt(self):
        parser = OptionParser()

        parser.add_option("-b", "--binaryDir", action="store",
                          type="string",
                          dest="binaryDir",
                          help="Specify the location of source code, or download it from github")

        (options, args) = parser.parse_args()

        if options.binaryDir:
            print("The binary dir is %s/package" % (options.binaryDir))
            self.binaryDir = options.binaryDir
            self.pkgDir  = self.binaryDir + "/package/"

    def DistributionType(self):
        result = os.popen('lsb_release -is').read().strip()
        if (result == 'Ubuntu'):
            return result
        elif (result == 'RedHatEnterprise' or result == 'RedHatEnterpriseWorkstation'):
            return 'RHEL'
        else:
            print('Unknown Linux distribution: ' + result)
            sys.exit(-1)

    def MakeDebPackage(self, arch):
        if not os.path.exists(self.pkgDir):
            raise Exception (self.pkgDir + ' does not exists, please create it and install driver contents there.')
        os.chdir(self.pkgDir)

        os.makedirs('DEBIAN')

        debControl = Control.replace(DriverVersionStub, self.version).replace(ArchitectureStub, arch)
        control_file = open("DEBIAN/control",'w')
        control_file.write(debControl + '\n')
        control_file.close()

        pkg_content = os.path.join(icdInstallDir, icdName) + ' ' + os.path.join(jsonInstallDir, jsonName)  + ' ' \
                      + os.path.join(docInstallDir,'changelog') + ' ' + os.path.join(docInstallDir, 'LICENSE.txt') + ' '
        os.system('md5sum ' + pkg_content + '> DEBIAN/md5sums')

        os.chdir(self.binaryDir)
        os.system('dpkg -b ' + self.pkgDir + ' amdvlk_' + self.version + '_' + arch + '.deb')

    def ArchiveAmdllpcTools(self, arch):
        toolsDir = 'amdllpc_' + arch

        os.chdir(self.workDir)
        if os.path.exists(toolsDir):
            shutil.rmtree(toolsDir)
        os.makedirs(toolsDir)

        spvgenName      = 'spvgen.so'
        spvgenBuildDir  = 'xgl/rbuild64/spvgen' if arch == 'amd64' else 'xgl/rbuild32/spvgen'
        amdllpcName     = 'amdllpc'
        amdllpcBuildDir = 'xgl/rbuild64/compiler/llpc' if arch == 'amd64' else 'xgl/rbuild32/compiler/llpc'

        os.system('cp ' + os.path.join(self.srcDir, amdllpcBuildDir, amdllpcName) + ' ' + toolsDir)
        os.system('cp ' + os.path.join(self.srcDir, spvgenBuildDir, spvgenName) + ' ' + toolsDir)
        os.system('zip -r ' + toolsDir + '.zip ' + toolsDir)

    def MakeRpmPackage(self):
        rpmbuild_dir = os.path.join(os.getenv('HOME'), 'rpmbuild')
        rpmbuildroot_dir = 'BUILDROOT'
        rpmspec_dir = 'SPEC'
        rpmspec_file_name = 'amdvlk.spec'
        icd_install_dir = 'usr/lib64'
        doc_install_dir = 'usr/share/doc/amdvlk'
        json_install_dir = 'etc/vulkan/icd.d'
        implicit_layer_dir = 'etc/vulkan/implicit_layer.d'
        icd_name = 'amdvlk64.so'
        json_name = 'amd_icd64.json'

        if os.path.exists(rpmbuild_dir):
            shutil.rmtree(rpmbuild_dir)
        os.makedirs(rpmbuild_dir)
        os.chdir(rpmbuild_dir)
        os.makedirs(rpmbuildroot_dir)
        os.makedirs(rpmspec_dir)

        rpm_spec = SPEC.replace(DriverVersionStub, self.version)
        spec_file = open(os.path.join(rpmspec_dir, rpmspec_file_name), 'w')
        spec_file.write(rpm_spec + '\n')
        spec_file.close()

        os.chdir(rpmbuildroot_dir)
        packagename = 'amdvlk-' + self.version + '-el.x86_64'
        os.makedirs(packagename)
        os.chdir(packagename)
        os.makedirs(icd_install_dir)
        os.makedirs(doc_install_dir)
        os.makedirs(json_install_dir)
        os.makedirs(implicit_layer_dir)

        os.system('cp ' + os.path.join(self.srcDir, 'xgl/rbuild64/icd', icd_name) + ' ' + icd_install_dir)
        os.system('strip ' + os.path.join(icd_install_dir, icd_name))
        os.system('cp ' + os.path.join(self.srcDir, 'AMDVLK/json/Redhat', json_name) + ' ' + json_install_dir)
        #os.system('cp ' + os.path.join(self.srcDir, 'AMDVLK/json/Redhat', json_name) + ' ' + implicit_layer_dir)

        os.system('cp ' + os.path.join(self.pkgSharedDir, 'changelog') + ' ' + doc_install_dir)
        os.system('cp ' + os.path.join(self.pkgSharedDir, 'copyright') + ' ' + doc_install_dir)

        os.chdir(rpmbuild_dir)
        os.chdir(rpmspec_dir)
        os.system('rpmbuild -bb ' + rpmspec_file_name)
        os.chdir(rpmbuild_dir)
        os.system('cp RPMS/x86_64/' + packagename + '.rpm ' + self.workDir)

    def Package(self):
        if (self.distro == 'Ubuntu'):
            self.MakeDebPackage('amd64')
            self.ArchiveAmdllpcTools('amd64')
            #self.MakeDebPackage('i386')
            #self.ArchiveAmdllpcTools('i386')
        elif (self.distro == 'RHEL'):
            self.MakeRpmPackage()

    def start(self):
        self.GetOpt()
        self.Package()

if __name__ == '__main__':
    worker = Worker()
    worker.start()

