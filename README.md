
Saudi Arabian E-Invoicing (ZATCA Phase-2) – A Frappe ERPNext App

A Frappe ERPNext app for businesses in Saudi Arabia, ensuring compliance with ZATCA Phase-2 e-invoicing regulations.

🚀 Features

✅ Compliance with ZATCA E-Invoicing Phase-2 <br>
✅ Integration with ZATCA APIs for clearance & reporting <br>
✅ Automatic CSR generation & compliance checks<br>
✅ Secure authentication & token management<br>
✅ Invoice submission for clearance & reporting<br>
✅ Support for standard invoices, credit notes, debit notes, Advance Payment Invoice <br>
✅ Retrieve and attach QR Codes to invoices<br>
✅ Logging for audit trails & error handling<br>
✅ Reports to compare invoices with ZATCA portal statistics <br>

🔹 Version 4.0 Enhancements

Version 4.0 extends the original ERPGulf ZATCA 3.0 application with a
compatibility-focused implementation for real-world ERPNext sites **With significant improvements at all levels**:

✨ **Significant improvements** in XML, QR code, and handling various types of discounts.<br>
✨ **Reliable Saudi tax data** – ZATCA tax categories and exemption reasons are
  synchronized on Sales Taxes and Charges Templates and Item Tax Templates,
  with safe support for legacy field names. <br>
✨ **Customer validation controls** – optional company-level rules validate Saudi
  B2B buyer IDs, TIN/Tax ID relationships, UNN (700), and Arabic customer names,
  with Arabic translations and configurable warnings. <br>
✨ **National Address validation** – configurable validation for linked Company
  and Customer addresses, including Building Number, Postal Code, Short Address,
  and Arabic/English address compatibility. <br>
✨ **Advance-payment workflow** – Payment Entries can create linked advance
  Sales Invoices, with ADV- naming, account and VAT consistency checks, safe
  allocation to final invoices, and return/credit-note handling. <br>
✨ **One consistent QR/XML path** – Sales Invoices use the ZATCA generator as
  the single QR source, retain one `ksa_einv_qr` attachment, and support local
  QR regeneration without contacting ZATCA. <br>
✨ **Correct machine timestamps** – XML IssueTime and QR Tag 3 preserve the
  invoice posting time in 24-hour `HH:mm:ss` form without accidental AM/PM
  conversion. <br>
✨ **Clearance and Reporting controls** – Phase-2 Clearance selection, B2C
  submission modes, response translation, debug XML, and improved error
  diagnostics are available from Company settings. <br>
✨ **Legacy-site hardening** – idempotent migrations normalize layouts,
  permissions, translations, naming series, and stale fetch mappings without
  changing existing transaction values. <br>
✨ **Regression coverage** – automated tests cover advance invoices, tax-source
  priority, field compatibility, QR TLV payloads, layouts, and validation rules. <br>

🔹 Compatibility<br>
🌐 ERPNext Version13, 14 and 15<br>
🖥️ Platforms	Ubuntu, Centos, Oracle Linux<br>

🛠 Installation Configuration & Setup

🔹 For Frappe Cloud Users

Frappe Cloud users can install the app directly from the Marketplace.

🔹 Build cloud server in Jeddah or Riyadh with  ERPNext & Zatca using Claudion https://saudi.claudion.com/onboarding 


🔹 For Self-Hosted ERPNext Users

Follow the standard Frappe app installation process:

# Get the app from GitHub
bench get-app https://github.com/Top1ERP/zatca_erpgulf.git

# Install the app on your site
bench --site yoursite.erpgulf.com install-app zatca_erpgulf

# Apply necessary migrations
bench --site yoursite.erpgulf.com migrate

# Restart bench or supervisor
bench restart 
or
sudo service supervisor restart


🔹 Verify Installation<br>
	1.	Login to ERPNext.<br>
	2.	Navigate to Help → About.<br>
	3.	Ensure the ZATCA app is listed.<br>

📈 Project Status

Feature	Details
🔓 License	MIT (Or another license)<br>
🌍 Website	https://erpgulf.com<br>
🛠 Maintenance<br>	✅ Actively Maintained<br>
🔄 PRs Welcome	<br>✅ Contributions Encouraged<br>
🏆 Open Source	✅

📺 Video Tutorial  https://www.youtube.com/watch?v=P0ChplXoKYg<br>
📺 Detailed documentation  https://docs.claudion.com/zatca%20pdf-a3<br>
📺 Handling Error messages from ZATCA  https://docs.claudion.com/Claudion-Docs/ErrorMessage1<br>
📺 Coding policy  https://docs.claudion.com/Claudion-Docs/Coding%20Policy<br>

🎥 Watch our step-by-step tutorial on YouTube:

🌟 Development & Contributions

We welcome contributions! To contribute:<br>
	1.	Fork this repository. <br>
	2.	Make your changes (improve the code, add features, fix bugs).<br>
	3.	Submit a Pull Request for review.<br>
	4.	If you find issues, please report them via the Issues section.<br>

Your contributions help make this project better! 🙌

📩 Support & Customization

For implementation support or customization, contact:
📧 Info@Top1ERP.com

👥 Social

🚀 Now you’re ready to be fully ZATCA-compliant! 🎯
