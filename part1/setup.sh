#!/bin/bash
set -e

echo "==> Installing packages"
apt-get update -qq
apt-get install -y python3 python3-pip python3-psycopg2 sudo --no-install-recommends -qq

echo "==> Creating users"
useradd -m -s /bin/bash alice
useradd -m -s /bin/bash bob
useradd -m -s /bin/bash carol
useradd -m -s /bin/bash david
useradd -m -s /bin/bash eve
useradd -m -s /bin/bash frank
useradd -m -s /bin/bash grace

echo "==> Creating groups"
groupadd developers
groupadd ops
groupadd finance
groupadd hr

echo "==> Assigning users to groups"
usermod -aG developers alice
usermod -aG developers bob
usermod -aG ops        carol
usermod -aG ops        david
usermod -aG finance    eve
usermod -aG finance    frank
usermod -aG hr         grace

echo "==> Creating directory structure"
mkdir -p /home/alice/docs
mkdir -p /home/alice/projects/web
mkdir -p /home/alice/projects/api
mkdir -p /home/alice/downloads
mkdir -p /home/bob/workspace/backend
mkdir -p /home/bob/workspace/scripts
mkdir -p /home/bob/notes
mkdir -p /home/bob/tmp
mkdir -p /home/carol/scripts/backup
mkdir -p /home/carol/scripts/deploy
mkdir -p /home/carol/logs
mkdir -p /home/carol/configs
mkdir -p /home/david/monitoring/alerts
mkdir -p /home/david/docs
mkdir -p /home/david/runbooks
mkdir -p /home/eve/reports/q1
mkdir -p /home/eve/reports/q2
mkdir -p /home/eve/reports/q3
mkdir -p /home/eve/spreadsheets
mkdir -p /home/frank/invoices/2024
mkdir -p /home/frank/invoices/2025
mkdir -p /home/frank/contracts
mkdir -p /home/frank/templates
mkdir -p /home/grace/policies/hr
mkdir -p /home/grace/policies/it
mkdir -p /home/grace/forms/onboarding
mkdir -p /home/grace/forms/leave

echo "==> Seeding files — alice"
echo "Q1 2025 Sales Summary"       > /home/alice/docs/q1-summary.txt
echo "API design draft v2"         > /home/alice/docs/api-design.md
echo "PostgreSQL migration notes"  > /home/alice/docs/db-notes.txt
echo "Landing page component"      > /home/alice/projects/web/index.html
echo "Auth middleware"             > /home/alice/projects/api/auth.py
echo "Rate limiter"                > /home/alice/projects/api/limiter.py
echo "Ubuntu 24.04 ISO"            > /home/alice/downloads/ubuntu.iso
echo "VSCode settings"             > /home/alice/downloads/settings.json

echo "==> Seeding files — bob"
echo "User service"                > /home/bob/workspace/backend/users.py
echo "Archive service"             > /home/bob/workspace/backend/archive.py
echo "DB models"                   > /home/bob/workspace/backend/models.py
echo "Deploy script"               > /home/bob/workspace/scripts/deploy.sh
echo "Healthcheck script"          > /home/bob/workspace/scripts/health.sh
echo "Sprint 12 notes"             > /home/bob/notes/sprint-12.txt
echo "Meeting notes 2025-06-10"    > /home/bob/notes/meeting-20250610.txt
echo "Old build artifact"          > /home/bob/tmp/build-old.tar.gz

echo "==> Seeding files — carol"
echo "Nightly backup cron"         > /home/carol/scripts/backup/nightly.sh
echo "S3 sync script"              > /home/carol/scripts/backup/s3-sync.sh
echo "Blue-green deploy"           > /home/carol/scripts/deploy/blue-green.sh
echo "Rollback script"             > /home/carol/scripts/deploy/rollback.sh
echo "App logs June"               > /home/carol/logs/app-2025-06.log
echo "Error logs June"             > /home/carol/logs/error-2025-06.log
echo "Nginx config"                > /home/carol/configs/nginx.conf
echo "Postgres config"             > /home/carol/configs/pg.conf

echo "==> Seeding files — david"
echo "Grafana dashboard JSON"      > /home/david/monitoring/alerts/dashboard.json
echo "Alert rules YAML"            > /home/david/monitoring/alerts/rules.yaml
echo "Incident report 2025-05-20"  > /home/david/docs/incident-20250520.md
echo "Capacity planning Q3"        > /home/david/docs/capacity-q3.md
echo "DB failover runbook"         > /home/david/runbooks/db-failover.md
echo "Network outage runbook"      > /home/david/runbooks/network-outage.md

echo "==> Seeding files — eve"
echo "Q1 Revenue report"           > /home/eve/reports/q1/revenue.xlsx
echo "Q1 Expenses"                 > /home/eve/reports/q1/expenses.xlsx
echo "Q2 Revenue report"           > /home/eve/reports/q2/revenue.xlsx
echo "Q2 Forecast"                 > /home/eve/reports/q2/forecast.xlsx
echo "Q3 Draft"                    > /home/eve/reports/q3/draft.xlsx
echo "Budget tracker 2025"         > /home/eve/spreadsheets/budget.xlsx
echo "Headcount model"             > /home/eve/spreadsheets/headcount.xlsx

echo "==> Seeding files — frank"
echo "Invoice INV-2024-0891"       > /home/frank/invoices/2024/INV-2024-0891.pdf
echo "Invoice INV-2024-0892"       > /home/frank/invoices/2024/INV-2024-0892.pdf
echo "Invoice INV-2025-0001"       > /home/frank/invoices/2025/INV-2025-0001.pdf
echo "Invoice INV-2025-0002"       > /home/frank/invoices/2025/INV-2025-0002.pdf
echo "Vendor contract Safaricom"   > /home/frank/contracts/safaricom-2025.pdf
echo "Vendor contract AWS"         > /home/frank/contracts/aws-2025.pdf
echo "Invoice template"            > /home/frank/templates/invoice.docx

echo "==> Seeding files — grace"
echo "Employee handbook v3"        > /home/grace/policies/hr/handbook-v3.pdf
echo "Leave policy 2025"           > /home/grace/policies/hr/leave-policy.pdf
echo "IT acceptable use policy"    > /home/grace/policies/it/acceptable-use.pdf
echo "Remote work policy"          > /home/grace/policies/it/remote-work.pdf
echo "Onboarding form template"    > /home/grace/forms/onboarding/template.pdf
echo "Leave request form"          > /home/grace/forms/leave/leave-request.pdf

echo "==> Setting ownership"
chown -R alice:alice  /home/alice
chown -R bob:bob      /home/bob
chown -R carol:carol  /home/carol
chown -R david:david  /home/david
chown -R eve:eve      /home/eve
chown -R frank:frank  /home/frank
chown -R grace:grace  /home/grace

FILE_COUNT=$(find /home -type f | wc -l)
echo ""
echo "========================================"
echo " Test environment ready"
echo " Groups:  developers / ops / finance / hr"
echo " Users:   alice, bob     -> developers"
echo "          carol, david   -> ops"
echo "          eve, frank     -> finance"
echo "          grace          -> hr"
echo " Files:   ${FILE_COUNT} files across all home dirs"
echo "========================================"

tail -f /dev/null