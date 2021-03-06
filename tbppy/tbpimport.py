# arch-tag: tla buildpackage import utilities
# Copyright (C) 2003 John Goerzen
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307 USA

import re, sys, os
import extcmd, tbpconfig, tla, versions, configs
from tla_support.commandver import cmd

def parsedsc(filename):
    fd = open(filename)
    retval = {}
    lastline = None
    for line in fd:
        line = line.rstrip()
        if line.startswith(' ') and lastline:
            retval[lastline].append(line.strip())
        else:
            m = re.search("^([a-zA-Z]+): *(.*)$", line)
            if m:
                if m.group(1) in retval:
                    # Bah, Version: also occurs in a signature.
                    lastline = None
                    continue
                if not len(m.group(2)):
                    retval[m.group(1)] = []
                else:
                    retval[m.group(1)] = [m.group(2)]
                lastline = m.group(1)
    return retval

def rmrf(dirname):
    print "Removing temporary directory %s..." % dirname
    extcmd.qrun('rm -fr "%s"' % dirname)

def importdsc(dscname):
    """Imports the original source into both upstream and Debian
    locations.

    Side effect: chdir to wc"""
    dscname = os.path.abspath(dscname)
    wc = os.path.abspath(tbpconfig.getwcdir())
    dscinfo = parsedsc(dscname)
    origtar = None
    for item in dscinfo['Files']:
        md5sum, size, filename = item.split(' ')
        if filename.endswith('tar.gz'):
            origtar = filename
    if origtar == None:
        print "Could not find orig.tar.gz in dsc file; aborting."
        sys.exit(20)

    origtar = os.path.join(os.path.dirname(dscname), origtar)
    importorigtargz(origtar, dscinfo['Source'][0],
                    versions.getupstreamver(dscinfo['Version'][0]))

    # OK, upstream is in there.  Now handle the Debian side of things.

    os.chdir(wc)
    archive = tla.getarchive()
    tlaupstreamrev = extcmd.run('tla cfgcat upstream/%s/%s' % \
                                (dscinfo['Source'][0],
                                 versions.getupstreamver(dscinfo['Version'][0])))
    tlaupstreamrev = tlaupstreamrev[0].split("\t")[1].strip()
    tlaupstreamver = re.search('^(.+)--.+$', tlaupstreamrev).group(1)
    tladebianver = "%s/%s--debian--1.0" % (archive, dscinfo['Source'][0])
    isnew = tla.condsetup(tladebianver)
    configs.makepkgconfigifneeded('debian', dscinfo['Source'][0])
    if not configs.checkversion('debian', dscinfo['Source'][0],
                                dscinfo['Version'][0]):
        print "Debian import: version %s is not newer than all versions in archive" % dscinfo['Version'][0]
        print "Will not import Debian because of this."
        return

    if isnew:
        extcmd.qrun('tla tag "%s" "%s"' % (tlaupstreamrev, tladebianver))
    
    tmpdir = os.path.join(wc, ",,tbp-importdeb")
    os.mkdir(tmpdir)
    try:
        os.chdir(tmpdir)
        extcmd.qrun('dpkg-source -x "%s"' % dscname)
        for item in os.listdir(tmpdir):
            if not item.endswith('tar.gz'):
                debsrcdir = os.path.abspath(item)
        tmpwcdir = os.path.join(tmpdir, ",,tbp-importdeb-wc")
        extcmd.qrun('tla get "%s" "%s"' % (tladebianver, tmpwcdir))
        os.chdir(tmpwcdir)
        if os.path.isfile('debian/changelog'):
            oldver = versions.getverfromchangelog()
        else:
            # First import -- just tagged, no Debian version.
            oldver = 'TPBIMPORTFAKE'
        if versions.getupstreamver(oldver) != \
           versions.getupstreamver(dscinfo['Version'][0]):
            # OK, our current tree doesn't use the same upstream
            # version as the new one.  So we need to fix.
            #extcmd.qrun('tla star-merge "%s"' % tlaupstreamrev)
            # FIXME: when we get tla 1.1, use tlaupstreamrev to be more
            # precise.
            try:
                extcmd.qrun('tla %s "%s"' % \
                            (cmd().replay, tlaupstreamver))
            except RuntimeError:
                pass
            #extcmd.qrun('tla update --in-place . "%s"' % tlaupstreamrev)
            for file in extcmd.run('tla inventory -b'):
                # Delete orig, rej files
                file = file.rstrip()
                os.unlink(file)
        os.chdir(tmpdir)
        extcmd.qrun('tla_load_dirs --wc="%s" --summary="Import Debian %s version %s" "%s"' % \
                    (tmpwcdir, dscinfo['Source'][0], dscinfo['Version'][0], debsrcdir))
        os.chdir(tmpwcdir)
        newrev_base = extcmd.run('tla revisions')[-1]
        newrev = "%s--%s" % (tladebianver, newrev_base)
        print "Committed %s" % newrev
    finally:
        os.chdir(wc)
        rmrf(tmpdir)

    os.chdir(wc)
    configs.writeconfig('debian', dscinfo['Source'][0], dscinfo['Version'][0],
                        newrev)
    configs.writelatest('debian', dscinfo['Source'][0], dscinfo['Version'][0],
                        tladebianver)
    extcmd.qrun('tla commit -L "Added configs for Debian %s %s"' % \
                (dscinfo['Source'][0], dscinfo['Version'][0]))


def importorigtargz(tarname, package, version):
    """Imports the original source stored in the file named by tarname.

    Side effect: chdir to wc"""
    tarname = os.path.abspath(tarname)
    wc = os.path.abspath(tbpconfig.getwcdir())

    tmpdir = os.path.join(wc, ",,tbp-importorigtargz")
    os.mkdir(tmpdir)
    try:
        os.chdir(tmpdir)
        extcmd.qrun('tar -zxSpf "%s"' % tarname)
        if len(os.listdir(tmpdir)) > 1:
            # If it has more than one entry, this directory itself is source,
            # since the tar didn't put things under one dir.  Bad, bad tar.
            srcdir = tmpdir
        else:
            srcdir = os.path.join(tmpdir, os.listdir(tmpdir)[0])
        importorigdir(srcdir, package, version)
    finally:
        os.chdir(wc)
        rmrf(tmpdir)

def importorigdir(dirname, package, version):
    """Imports the original source stored in directory dirname.

    Side-effect: chdir to wc"""
    print " *** Import upstream package %s version %s from directory %s" % (package, version, dirname)
    dirname = os.path.abspath(dirname)
    wc = os.path.abspath(tbpconfig.getwcdir())
    os.chdir(wc)

    archive = tla.getarchive()
    tlaversion = "%s/%s--head--1.0" % (archive, package)
    print "tla version will be %s" % tlaversion

    isnew = tla.condsetup(tlaversion)

    # If it's new, need to create empty dir and then tla_load_dirs
    # into it.  Otherwise, check out latest and tla_load_dirs into that.
    #
    # After doing that, update the config file and commit.
    
    configs.makepkgconfigifneeded('upstream', package)
    configs.makepkgdirifneeded(package)
    if not configs.checkversion('upstream', package, version):
        print "Upstream import: version %s is not newer than all versions in archive" % version
        print "Will not import upstream because of this."
        return

    # OK, we know it's OK....  Now, either create the new dir or check out
    # previous version.

    if os.path.exists(",,tbp-importorigdir"):
        print "Error: ,,tbp-importorigdir already exists; exiting."
        sys.exit(6)

    if isnew:
        os.mkdir(',,tbp-importorigdir')
    else:
        print "Getting latest version for comparison..."
        extcmd.qrun('tla get "%s" ,,tbp-importorigdir' % tlaversion)
        
    try:
        if isnew:
            print "Initializing storage area for upstream..."
            os.chdir(',,tbp-importorigdir')
            extcmd.qrun('tla init-tree --nested "%s"' % tlaversion)
            extcmd.qrun('tla %s explicit' % cmd().tagging_method)
            # Relax the source pattern...
            fd = open('{arch}/=tagging-method')
            lines = fd.readlines()
            fd.close()
            fd = open('{arch}/=tagging-method', 'w')
            for line in lines:
                if line.startswith('source '):
                    fd.write(r'source (^[._=a-zA-Z0-9!#-].*$|^\.gdbinit)')
                    fd.write("\n")
                elif line.startswith('backup '):
                    fd.write(r'backup ^$')
                    fd.write("\n")
                else:
                    fd.write(line)
            fd.close()
            extcmd.qrun('tla import')
            os.chdir(wc)
        extcmd.qrun('tla_load_dirs --wc="%s/,,tbp-importorigdir" --summary="Import upstream %s version %s" "%s"' % \
                (wc, package, version, dirname))
        os.chdir('%s/,,tbp-importorigdir' % wc)
        newrev_base = extcmd.run('tla revisions')[-1]
        newrev = "%s--%s" % (tlaversion, newrev_base)
        print "Committed %s" % newrev
    finally:
        os.chdir(wc)
        rmrf("%s/,,tbp-importorigdir" % wc)
        
    # Now add a config for this version.

    os.chdir(wc)
    
    configs.writeconfig('upstream', package, version, newrev)
    configs.writelatest('upstream', package, version, tlaversion)

    extcmd.qrun('tla commit -L "Added configs for upstream %s %s"' % \
                (package, version))
    
