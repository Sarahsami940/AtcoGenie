<#
.SYNOPSIS
    Provisions Service Accounts and SPNs for Atco Genie.
    Run this on a Domain Controller or a machine with RSAT-AD-PowerShell installed.
    Requires Domain Admin privileges.

.DESCRIPTION
    1. Creates/Updates SVC_Genie_App (App Pool Identity).
    2. Creates/Updates SVC_Genie_Sync (Background Worker Identity).
    3. Registers HTTP SPN for Kerberos Authentication.
#>

param(
    [string]$Domain = "ATCO",
    [string]$ServicePassword = "ChangeMe123!", -- CHANGE THIS IN PRODUCTION
    [string]$AppServerHostName = "genie-app-01.atco.local" -- The VM Hostname
)

Import-Module ActiveDirectory

# 1. Create SVC_Genie_App
$appName = "SVC_Genie_App"
try {
    Get-ADUser -Identity $appName -ErrorAction Stop
    Write-Host "Service Account $appName already exists." -ForegroundColor Yellow
}
catch {
    Write-Host "Creating Service Account $appName..." -ForegroundColor Green
    New-ADUser -Name $appName -SamAccountName $appName -UserPrincipalName "$appName@$Domain.com" -AccountPassword (ConvertTo-SecureString $ServicePassword -AsPlainText -Force) -Enabled $true -PasswordNeverExpires $true -Description "Service Account for Atco Genie Web App"
}

# 2. Create SVC_Genie_Sync
$syncName = "SVC_Genie_Sync"
try {
    Get-ADUser -Identity $syncName -ErrorAction Stop
    Write-Host "Service Account $syncName already exists." -ForegroundColor Yellow
}
catch {
    Write-Host "Creating Service Account $syncName..." -ForegroundColor Green
    New-ADUser -Name $syncName -SamAccountName $syncName -UserPrincipalName "$syncName@$Domain.com" -AccountPassword (ConvertTo-SecureString $ServicePassword -AsPlainText -Force) -Enabled $true -PasswordNeverExpires $true -Description "Service Account for Atco Genie Background Sync"
}

# 3. Register SPNs (Service Principal Names)
# Essential for Kerberos. We register HTTP/Hostname to the App Account.

$spn = "HTTP/$AppServerHostName"
Write-Host "Registering SPN: $spn for $appName" -ForegroundColor Cyan

# Check if SPN exists
$spnCheck = Get-ADUser -Filter {ServicePrincipalNames -like $spn} -Properties ServicePrincipalNames
if ($spnCheck) {
    Write-Host "SPN $spn is already registered to $($spnCheck.SamAccountName)" -ForegroundColor Yellow
}
else {
    # Register SPN
    # Usage: setspn -S HTTP/my-web-server SVC_Genie_App
    # Using PowerShell AD Cmdlet:
    Set-ADUser -Identity $appName -Add @{ServicePrincipalNames=$spn}
    Write-Host "SPN Registered Successfully." -ForegroundColor Green
}

# 4. Delegation (Optional - if we need Double Hop)
# Write-Host "Configure Unconstrained/Constrained Delegation if needed in AD Users & Computers."
