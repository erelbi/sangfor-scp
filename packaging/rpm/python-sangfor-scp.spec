Name:           python-sangfor-scp
Version:        0.4.2
Release:        1%{?dist}
Summary:        Python client for the Sangfor Cloud Platform (SCP) Open-API

License:        MIT
URL:            https://github.com/erelbi/sangfor-scp
Source0:        sangfor_scp-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-pytest

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


%generate_buildrequires
%pyproject_buildrequires


%build
%pyproject_wheel


%install
%pyproject_install
%pyproject_save_files -l sangfor_scp


%check
%pyproject_check_import
%pytest tests


%files -n python3-sangfor-scp -f %{pyproject_files}
%doc README.md CONTRIBUTING.md SECURITY.md
%{_bindir}/scp-health


%changelog
* Wed Oct 21 2026 sangfor-scp maintainers <erelbi@users.noreply.github.com> - 0.4.2-1
- metrics: stop_time is platform local time; windows older than or crossing the 24h mark now work

* Mon Oct 19 2026 sangfor-scp maintainers <erelbi@users.noreply.github.com> - 0.4.1-1
- Initial RPM package
- Token authentication also works with pycryptodomex (Cryptodome)
