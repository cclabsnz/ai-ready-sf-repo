trigger CaseTrigger on Case (before update, after update) {
    CaseTriggerHandler.handle(Trigger.operationType, Trigger.new, Trigger.oldMap);
}
