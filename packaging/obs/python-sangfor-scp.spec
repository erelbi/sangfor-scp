#
# spec file for package python-sangfor-scp
#
# Copyright (c) 2026 Ergün Elvan Bilsel
#
# All modifications and additions to the file contributed by third parties
# remain the property of their copyright owners, unless otherwise agreed
# upon. The license for this file, and modifications and additions to the
# file, is the same license as for the pristine package itself (unless the
# license for the pristine package is not an Open Source License, in which
# case the license is the MIT License).
#
# Please submit bugfixes or comments via https://github.com/erelbi/sangfor-scp/issues
#


%{?sle15_python_module_pythons}
Name:           python-sangfor-scp
Version:        0.4.5
Release:        0
Summary:        Python client for the Sangfor Cloud Platform (SCP) Open-API
License:        MIT
URL:            https://github.com/erelbi/sangfor-scp
Source:         https://files.pythonhosted.org/packages/source/s/sangfor_scp/sangfor_scp-%{version}.tar.gz
BuildRequires:  %{python_module pip}
BuildRequires:  %{python_module setuptools >= 61}
BuildRequires:  %{python_module wheel}
BuildRequires:  fdupes
BuildRequires:  python-rpm-macros
# Tests
BuildRequires:  %{python_module pycryptodome}
BuildRequires:  %{python_module pytest}
BuildRequires:  %{python_module requests >= 2.28.0}
BuildRequires:  %{python_module urllib3 >= 1.26.0}
Requires:       python-requests >= 2.28.0
Requires:       python-urllib3 >= 1.26.0
Requires(post): update-alternatives
Requires(postun): update-alternatives
# Token (username/password) authentication encrypts the password with RSA
Recommends:     python-pycryptodome
BuildArch:      noarch
%python_subpackages

%description
sangfor-scp is a Python client library for the Sangfor Cloud Platform (SCP)
Open-API. It covers virtual machines (create, clone, migrate, power, console),
networks, images, volumes, elastic IPs, tasks, alarms and monitoring metrics,
with EC2 (AWS4-HMAC-SHA256) and token authentication, automatic pagination and
asynchronous task polling.

It also ships the scp-health command, a read-only platform health report
(alarms, VM disk usage, failed tasks, host CPU generations, capacity).

%prep
%autosetup -p1 -n sangfor_scp-%{version}
# setuptools older than 77 does not understand the PEP 639 license fields
# (license = "MIT", license-files); convert them to the older table form.
if ! python3 -c 'import setuptools, sys; sys.exit(int(setuptools.__version__.split(".")[0]) < 77)' 2>/dev/null; then
  sed -i -e 's/^license = "MIT"$/license = {text = "MIT"}/' -e '/^license-files = /d' \
      -e 's/"setuptools>=68"/"setuptools>=61"/' pyproject.toml
fi

%build
%pyproject_wheel

%install
%pyproject_install
install -Dpm 0644 man/scp-health.1 %{buildroot}%{_mandir}/man1/scp-health.1
%python_clone -a %{buildroot}%{_bindir}/scp-health
%python_clone -a %{buildroot}%{_mandir}/man1/scp-health.1
%python_expand %fdupes %{buildroot}%{$python_sitelib}

%check
%pytest tests

%post
%python_install_alternative scp-health scp-health.1

%postun
%python_uninstall_alternative scp-health

%files %{python_files}
%license LICENSE
%doc README.md CONTRIBUTING.md SECURITY.md
%python_alternative %{_bindir}/scp-health
%python_alternative %{_mandir}/man1/scp-health.1%{?ext_man}
%{python_sitelib}/sangfor_scp
%{python_sitelib}/sangfor_scp-%{version}.dist-info

%changelog
