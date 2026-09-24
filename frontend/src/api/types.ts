import type { components } from "./schema";

type S = components["schemas"];

export type Category = S["Category"];
export type CategoryKind = S["CategoryKindEnum"];
export type Component = S["Component"];
export type ComponentBrief = S["ComponentBrief"];
export type BuildList = S["BuildList"];
export type BuildDetail = S["BuildDetail"];
export type BuildWrite = S["BuildWriteRequest"];
export type BuildItemWrite = S["BuildItemWriteRequest"];
export type CompatibilityReport = S["CompatibilityReport"];
export type Issue = S["Issue"];
export type Comment = S["Comment"];
export type Order = S["Order"];
export type PaymentSession = S["PaymentSession"];
export type AdvisorRequest = S["AdvisorRequest"];
export type AdvisorResponse = S["AdvisorResponse"];
export type User = S["User"];
export type CategoryStats = S["CategoryStats"];
export type PopularComponent = S["PopularComponent"];
export type Watch = S["Watch"];
export type TelegramStatus = S["TelegramStatus"];
