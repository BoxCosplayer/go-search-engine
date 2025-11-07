# escape=`

ARG PYTHON_IMAGE=mcr.microsoft.com/windows/python:3.11-windowsservercore-ltsc2022
ARG RUNTIME_IMAGE=mcr.microsoft.com/windows/servercore:ltsc2022

FROM ${PYTHON_IMAGE} AS build
SHELL ["powershell", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]
WORKDIR C:\\src

COPY requirements.txt .

RUN python -m pip install --upgrade pip; `
    pip install --no-cache-dir -r requirements.txt; `
    pip install --no-cache-dir pyinstaller

COPY . .

RUN if (-not (Test-Path 'config.json') -and (Test-Path 'config-template.txt')) { `
        Copy-Item 'config-template.txt' 'config.json' `
    } elseif (-not (Test-Path 'config.json')) { `
        '{\"host\":\"0.0.0.0\",\"port\":5000,\"debug\":false,\"db-path\":\"links.db\",\"allow-files\":false,\"fallback-url\":\"\",\"file-allow\":[]}' `
            | Set-Content -Path 'config.json' -Encoding utf8NoBOM `
    }

RUN pyinstaller go-server.spec

FROM ${RUNTIME_IMAGE} AS runtime
SHELL ["powershell", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]
WORKDIR C:\\app

COPY --from=build C:\\src\\dist\\go-server.exe .\\
COPY config-template.txt .\\
COPY docker\\entrypoint.ps1 C:\\entrypoint.ps1

ENV GO_CONFIG_PATH=C:\\data\\config.json
EXPOSE 5000
VOLUME ["C:\\data"]

ENTRYPOINT ["powershell", "-NoLogo", "-NoProfile", "-File", "C:\\entrypoint.ps1"]
