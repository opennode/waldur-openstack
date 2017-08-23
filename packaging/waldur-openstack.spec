Name: waldur-openstack
Summary: OpenStack plugin for Waldur
Group: Development/Libraries
Version: 0.34.0
Release: 1.el7
License: MIT
Url: http://waldur.com
Source0: %{name}-%{version}.tar.gz

Requires: waldur-core >= 0.145.5
Requires: python-ceilometerclient >= 2.3.0
Requires: python-cinderclient >= 1.6.0
Requires: python-cinderclient < 2.0.0
Requires: python-glanceclient >= 1:2.0.0
Requires: python-iptools >= 0.6.1
Requires: python-keystoneclient >= 1:2.3.1
Requires: python-neutronclient >= 4.1.1
Requires: python-novaclient >= 1:3.3.0
Requires: python-novaclient < 1:3.4.0

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
