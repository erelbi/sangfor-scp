Name:           python-sangfor-scp
Version:        0.4.4
Release:        1%{?dist}
Summary:        Python client for the Sangfor Cloud Platform (SCP) Open-API

License:        MIT
URL:            https://github.com/erelbi/sangfor-scp
Source:         %{pypi_source sangfor_scp}

BuildArch:      noarch
BuildRequires:  python3-devel
# The tests only use unittest.mock, so pytest-mock is not needed
BuildRequires:  python3-pytest
%if 0%{?fedora}
# Lets %%check also run the RSA password encryption test (skipped without it)
BuildRequires:  python3-pycryptodomex
%endif

%global _description %{expand:
sangfor-scp is a Python client library for the Sangfor Cloud Platform (SCP)
Open-API. It covers virtual machines (create, clone, migrate, power, console),
networks, images, volumes, elastic IPs, tasks, alarms and monitoring metrics,
with EC2 (AWS4-HMAC-SHA256) and token authentication, automatic pagination and
async task polling.

It also ships the scp-health command, a read-only platform health report
(alarms, VM disk usage, failed tasks, host CPU generations, capacity).}

%description %_description

%package -n python3-sangfor-scp
Summary:        %{summary}
# Token (username/password) authentication encrypts the password with RSA
Recommends:     python3-pycryptodomex

%description -n python3-sangfor-scp %_description


%prep
%autosetup -n sangfor_scp-%{version}
%if 0%{?rhel} && 0%{?rhel} <= 10
# setuptools 69 on EL10 does not understand the PEP 639 license fields
# (license = "MIT", license-files); convert them to the older table form.
# The LICENSE file is still picked up automatically.
sed -i -e 's/^license = "MIT"$/license = {text = "MIT"}/' -e '/^license-files = /d' pyproject.toml
%endif


%generate_buildrequires
%pyproject_buildrequires


%build
%pyproject_wheel


%install
%pyproject_install
%pyproject_save_files -l sangfor_scp
install -Dpm 0644 man/scp-health.1 %{buildroot}%{_mandir}/man1/scp-health.1


%check
%pyproject_check_import
%pytest tests


%files -n python3-sangfor-scp -f %{pyproject_files}
%doc README.md CONTRIBUTING.md SECURITY.md
%{_bindir}/scp-health
%{_mandir}/man1/scp-health.1*


%changelog
* Wed Oct 21 2026 Ergün Elvan Bilsel <bilselergun@gmail.com> - 0.4.4-1
- Add scp-health(1) man page

* Wed Oct 21 2026 Ergün Elvan Bilsel <bilselergun@gmail.com> - 0.4.3-1
- Add offline tests for EC2 signing, HTTP error mapping, pagination,
  task polling and token login
- Replace deprecated datetime.utcnow()
- Spec: English comments; BuildRequires pycryptodomex for %%check on Fedora

* Wed Oct 21 2026 Ergün Elvan Bilsel <bilselergun@gmail.com> - 0.4.2-1
- metrics: stop_time is platform local time; windows older than or crossing the 24h mark now work

* Mon Oct 19 2026 Ergün Elvan Bilsel <bilselergun@gmail.com> - 0.4.1-1
- Initial RPM package
- Token authentication also works with pycryptodomex (Cryptodome)
