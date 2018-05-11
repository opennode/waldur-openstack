Name: waldur-openstack
Summary: OpenStack plugin for Waldur
Group: Development/Libraries
Version: 0.42.0
Release: 1.el7
License: MIT
Url: http://waldur.com
Source0: %{name}-%{version}.tar.gz

Requires: waldur-core >= 0.157.5
Requires: python-ceilometerclient >= 2.9.0
Requires: python-cinderclient >= 3.1.0
Requires: python-glanceclient >= 1:2.8.0
Requires: python-iptools >= 0.6.1
Requires: python-keystoneclient >= 1:3.13.0
Requires: python-neutronclient >= 6.5.0
Requires: python-novaclient >= 1:9.1.0

Obsoletes: nodeconductor-openstack

BuildArch: noarch
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-buildroot

BuildRequires: python-setuptools

%description
OpenStack plugin for Waldur.

%prep
%setup -q -n %{name}-%{version}

%build
%{__python} setup.py build

%install
rm -rf %{buildroot}
%{__python} setup.py install -O1 --root=%{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python_sitelib}/*

%changelog
* Thu May 10 2018 Jenkins <jenkins@opennodecloud.com> - 0.42.0-1.el7
- New upstream release

* Thu Apr 12 2018 Jenkins <jenkins@opennodecloud.com> - 0.41.3-1.el7
- New upstream release

* Sun Apr 8 2018 Jenkins <jenkins@opennodecloud.com> - 0.41.2-1.el7
- New upstream release

* Fri Mar 23 2018 Jenkins <jenkins@opennodecloud.com> - 0.41.1-1.el7
- New upstream release

* Fri Mar 23 2018 Jenkins <jenkins@opennodecloud.com> - 0.41.0-1.el7
- New upstream release

* Mon Feb 26 2018 Jenkins <jenkins@opennodecloud.com> - 0.40.6-1.el7
- New upstream release

* Sat Feb 17 2018 Jenkins <jenkins@opennodecloud.com> - 0.40.5-1.el7
- New upstream release

* Tue Feb 13 2018 Jenkins <jenkins@opennodecloud.com> - 0.40.4-1.el7
- New upstream release

* Wed Feb 7 2018 Jenkins <jenkins@opennodecloud.com> - 0.40.3-1.el7
- New upstream release

* Tue Jan 30 2018 Jenkins <jenkins@opennodecloud.com> - 0.40.2-1.el7
- New upstream release

* Wed Jan 17 2018 Jenkins <jenkins@opennodecloud.com> - 0.40.1-1.el7
- New upstream release

* Sat Jan 13 2018 Jenkins <jenkins@opennodecloud.com> - 0.40.0-1.el7
- New upstream release

* Fri Dec 22 2017 Jenkins <jenkins@opennodecloud.com> - 0.39.0-1.el7
- New upstream release

* Fri Dec 1 2017 Jenkins <jenkins@opennodecloud.com> - 0.38.2-1.el7
- New upstream release

* Wed Nov 22 2017 Jenkins <jenkins@opennodecloud.com> - 0.38.1-1.el7
- New upstream release

* Mon Nov 20 2017 Jenkins <jenkins@opennodecloud.com> - 0.38.0-1.el7
- New upstream release

* Thu Nov 2 2017 Jenkins <jenkins@opennodecloud.com> - 0.37.5-1.el7
- New upstream release

* Sun Oct 29 2017 Jenkins <jenkins@opennodecloud.com> - 0.37.4-1.el7
- New upstream release

* Mon Oct 16 2017 Jenkins <jenkins@opennodecloud.com> - 0.37.3-1.el7
- New upstream release

* Tue Oct 10 2017 Jenkins <jenkins@opennodecloud.com> - 0.37.2-1.el7
- New upstream release

* Wed Oct 4 2017 Jenkins <jenkins@opennodecloud.com> - 0.37.1-1.el7
- New upstream release

* Sat Sep 30 2017 Jenkins <jenkins@opennodecloud.com> - 0.37.0-1.el7
- New upstream release

* Thu Sep 28 2017 Jenkins <jenkins@opennodecloud.com> - 0.36.1-1.el7
- New upstream release

* Wed Sep 27 2017 Jenkins <jenkins@opennodecloud.com> - 0.36.0-1.el7
- New upstream release

* Mon Sep 18 2017 Jenkins <jenkins@opennodecloud.com> - 0.35.1-1.el7
- New upstream release

* Sat Sep 16 2017 Jenkins <jenkins@opennodecloud.com> - 0.35.0-1.el7
- New upstream release

* Fri Aug 25 2017 Jenkins <jenkins@opennodecloud.com> - 0.34.2-1.el7
- New upstream release

* Thu Aug 24 2017 Jenkins <jenkins@opennodecloud.com> - 0.34.1-1.el7
- New upstream release

* Wed Aug 23 2017 Jenkins <jenkins@opennodecloud.com> - 0.34.0-1.el7
- New upstream release

* Tue Aug 8 2017 Jenkins <jenkins@opennodecloud.com> - 0.33.2-1.el7
- New upstream release

* Sun Aug 6 2017 Jenkins <jenkins@opennodecloud.com> - 0.33.1-1.el7
- New upstream release

* Sun Aug 6 2017 Jenkins <jenkins@opennodecloud.com> - 0.33.0-1.el7
- New upstream release

* Tue Aug 1 2017 Jenkins <jenkins@opennodecloud.com> - 0.32.0-1.el7
- New upstream release

* Mon Jul 17 2017 Jenkins <jenkins@opennodecloud.com> - 0.31.2-1.el7
- New upstream release

* Fri Jul 14 2017 Jenkins <jenkins@opennodecloud.com> - 0.31.1-1.el7
- New upstream release

* Wed Jul 12 2017 Jenkins <jenkins@opennodecloud.com> - 0.31.0-1.el7
- New upstream release

* Mon Jul 3 2017 Jenkins <jenkins@opennodecloud.com> - 0.30.2-1.el7
- New upstream release
