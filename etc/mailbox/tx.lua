-- SPDX-License-Identifier: Apache-2.0

local lua_mime = require "lua_mime"
local rspamd_logger = require "rspamd_logger"
local domain = assert(os.getenv("MAIL_DOMAIN")):lower():gsub("%.$", "")
local mode = os.getenv("MAIL_MODE") or "smtp_only"
local key = "/persist/mail/tx/platform.private"
local senders = "/persist/mail/control/senders"

local function own_addresses(login)
  local file = io.open(senders, "r")
  if not file then return nil end
  local addresses = {}
  for line in file:lines() do
    local owner, allowed = line:match("^([^:]+):(.*)$")
    if owner == login then
      for address in allowed:gmatch("[^%s:]+") do
        addresses[address:lower()] = true
      end
      break
    end
  end
  file:close()
  return addresses
end

local function permitted(addresses, address)
  return address and address.addr and addresses[address.addr:lower()]
end

local function authorize_and_sign(task)
  local login = task:get_user()
  if not login or login == "" then
    task:set_pre_result("reject", "SMTP authentication required")
    return
  end
  if mode == "mailbox" then
    local allowed = own_addresses(login)
    if not allowed then
      task:set_pre_result("soft reject", "Sender policy is temporarily unavailable")
      return
    end
    local envelope = task:get_from("smtp") or {}
    local from = task:get_from("mime") or {}
    local headers = #(task:get_header_full("From") or {})
    if #envelope ~= 1 or not permitted(allowed, envelope[1]) then
      task:set_pre_result("reject", "Envelope sender is not allowed")
      return
    end
    if headers ~= 1 or #from ~= 1 or not permitted(allowed, from[1]) then
      task:set_pre_result("reject", "A single authorized From address is required")
      return
    end
  end

  local ok, signature = rspamd_plugins.dkim.sign(task, {
    domain = domain, selector = "platform", key = key, no_cache = true,
  })
  if not ok or not signature then
    task:set_pre_result("soft reject", "DKIM signing temporarily unavailable")
    return
  end
  lua_mime.modify_headers(task, { add = { ["DKIM-Signature"] = { order = 1, value = signature } } })
end

rspamd_config:register_symbol({
  name = "EXORDOS_MAIL_TX", type = "postfilter",
  callback = function(task)
    if not pcall(authorize_and_sign, task) then
      rspamd_logger.errx(task, "SMTP sender policy or signing failed")
      task:set_pre_result("soft reject", "Mail submission temporarily unavailable")
    end
  end,
})
