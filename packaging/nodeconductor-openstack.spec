Name: nodeconductor-openstack
Summary: OpenStack plugin for NodeConductor
Group: Development/Libraries
Version: 0.5.1
Release: 1.el7
License: Copyright 2016 OpenNode LLC. All rights reserved.
Url: http://nodeconductor.com
Source0: %{name}-%{version}.tar.gz

Requires: nodeconductor > 0.102.5
Requires: python-ceilometerclient = 2.3.0
Requires: python-cinderclient = 1.6.0
Requires: python-glanceclient = 1:2.0.0
Requires: python-iptools >= 0.6.1
Requires: python-keystoneclient = 1:2.3.1
Requires: python-neutronclient = 4.1.1
Requires: python-novaclient = 1:3.3.0

BuildArch: noarch
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-buildroot

BuildRequires: python-setuptools


%description
OpenStack plugin for NodeConductor.

%prep
%setup -q -n %{name}-%{version}

%build
python setup.py build

%install
rm -rf %{buildroot}
%{__python} setup.py install -O1 --root=%{buildroot}

%clean
rm -rf %{buildroot}

%files
%defattr(-,root,root)
%{python_sitelib}/*

%changelog
* Thu Jul 28 2016 Jenkins <jenkins@opennodecloud.com> - 0.5.1-1.el7
- New upstream release

* Fri Jul 15 2016 Jenkins <jenkins@opennodecloud.com> - 0.5.0-1.el7
- New upstream release

* Thu Jul 7 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.10-1.el7
- New upstream release

* Thu Jul 7 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.9-1.el7
- New upstream release

* Wed Jul 6 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.8-1.el7
- New upstream release

* Tue Jul 5 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.7-1.el7
- New upstream release

* Tue Jul 5 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.6-1.el7
- New upstream release

* Mon Jul 4 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.5-1.el7
- New upstream release

* Thu Jun 30 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.4-1.el7
- New upstream release

* Thu Jun 30 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.3-1.el7
- New upstream release

* Thu Jun 30 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.2-1.el7
- New upstream release

* Thu Jun 30 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.1-1.el7
- New upstream release

* Wed Jun 29 2016 Jenkins <jenkins@opennodecloud.com> - 0.4.0-1.el7
- New upstream release

* Tue May 24 2016 Jenkins <jenkins@opennodecloud.com> - 0.3.0-1.el7
- New upstream release

* Mon May 16 2016 Jenkins <jenkins@opennodecloud.com> - 0.2.0-1.el7
- New upstream release

* Mon May 16 2016 Ilja Livenson <ilja@opennodecloud.com> - 0.1.0-1.el7
- Initial version of the package

