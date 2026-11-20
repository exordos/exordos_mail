# Развёртывание Exordos Mail

[English](deployment.md)

## Установка элемента

Выполните команду в Realm с установленным MetaPaaS. Чтобы выбрать
конкретную сборку элемента, добавьте `-v VERSION`.

```bash
exordos e e install mailaas
```

Дождитесь статуса элемента `ACTIVE`. MetaPaaS регистрирует API Mail
и доступные образы ВМ.

## Создание экземпляра

Оба режима используют образ версии `exim4_1`.

| Режим | Минимум vCPU | Минимум ОЗУ | Минимум для диска данных |
| ----- | ------------ | ----------- | ----------------------- |
| `smtp_only` | 1 | 512 МиБ | 8 ГиБ |
| `mailbox` | 2 | 1024 МиБ | 8 ГиБ |

Для `mailbox` начните с 2048 МиБ ОЗУ. Выделите место на диске данных под
содержимое ящиков и очереди доставки. В примере используется 20 ГиБ.

Задайте `MAIL_API` как базовый URL MetaPaaS с суффиксом `/v1/types/mail`
и запишите токен API в `TOKEN`. Передавайте учётные данные по HTTPS.
Запросите список версий образов и выберите UUID версии `exim4_1`.

```bash
curl --fail-with-body "$MAIL_API/versions/" -H "Authorization: Bearer $TOKEN"
```

Сохраните следующий JSON как `instance.json`, заменив `PROJECT_UUID` и
`VERSION_UUID`. Для режима отправки укажите `smtp_only` или опустите
`mode`. Домен задаётся при создании.

```json
{
  "name": "mail-prod",
  "project_id": "PROJECT_UUID",
  "mode": "mailbox",
  "domain": "example.org",
  "cpu": 2,
  "ram": 2048,
  "disk_size": 20,
  "version": "/v1/types/mail/versions/VERSION_UUID"
}
```

```bash
curl --fail-with-body "$MAIL_API/instances/" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data-binary @instance.json
```

Запишите UUID из ответа в `INSTANCE_UUID` и дождитесь статуса `ACTIVE`.
В ответе API `endpoints` содержит параметры подключения, а
`dkim_selector` и `dkim_public_key` задают запись DKIM.

```bash
curl --fail-with-body "$MAIL_API/instances/$INSTANCE_UUID" \
  -H "Authorization: Bearer $TOKEN" |
  jq '{status, endpoints, dkim_selector, dkim_public_key}'
```

## Создание ящика или учётной записи SMTP

Для ящика отправьте запрос
`POST /v1/types/mail/instances/INSTANCE_UUID/mailboxes/` с `local_part`
(например `alice`), `owner_user_uuid` и паролем. В необязательном поле
`aliases` перечислите локальные имена, например `sales`. В `project_id`
укажите проект экземпляра. Дождитесь статуса ящика
`ACTIVE` перед подключением.

Для отправки создайте учётную запись по адресу
`POST /v1/types/mail/instances/INSTANCE_UUID/accounts/` с `username`
(например `app`) и `password`. Используйте проект экземпляра. Храните
пароль в защищённом месте и передавайте его при создании или смене
пароля. См. [справочник API](../api/reference.ru.md).

## Подключение клиентов

Используйте имя хоста из `endpoints`. Для примера выше это
`mail.example.org`. Добавьте CA экземпляра в доверенные у клиентов. См. [работу с сертификатами](operations.ru.md).

| Протокол | Подключение | Логин ящика |
| -------- | ----------- | ----------- |
| SMTP submission | TCP 587 с STARTTLS | Основной адрес целиком, например `alice@example.org` |
| IMAP | TCP 993 с TLS с начала соединения | Локальная часть, например `alice` |
| CalDAV | `https://mail.example.org:8443/dav/calendars/` | Локальная часть, например `alice` |

В режиме `smtp_only` учётная запись SMTP подключается к порту 587
с STARTTLS и использует логин `username@домен`, например `app@example.org`.
В этом режиме также доступен SMTP на порту 465 с TLS с начала соединения.

## Записи DNS

| Запись | Имя | Значение |
| ------ | --- | -------- |
| A | `mail.example.org` | IPv4-адрес для подключения клиентов. Добавьте AAAA, если сервисы доступны через входную точку с IPv6. |
| SPF TXT | `example.org` | Разрешите фактический публичный IP отправки TX. Для одного IPv4-отправителя используйте `v=spf1 ip4:TX_PUBLIC_IP -all`. Добавьте остальные разрешённые источники. |
| DKIM TXT | `<dkim_selector>._domainkey.example.org` | Значение `dkim_public_key`. Селектор по умолчанию — `platform`. Длинное значение разбейте на строки до 255 байт в одной TXT-записи. |
| DMARC TXT | `_dmarc.example.org` | Начните с `v=DMARC1; p=none`, проверьте соответствие доменов в SPF и DKIM и выберите политику домена. |
| PTR | Публичный IP TX | Имя SMTP-сервера с соответствующей прямой записью. Настраивается у провайдера IP. |
| MX | `example.org` | Публичные имена входящих MX и их приоритеты для режима `mailbox`. Опубликуйте A или AAAA для каждого MX. |

Если TX работает за NAT, укажите в SPF и PTR фактический внешний IP.
Публичные IP входящих MX могут отличаться от IP отправки. Настройте
каждый [внешний MX](external-mx.ru.md) до публикации его имени в DNS.
