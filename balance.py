# ChatGPT 4o generated output from prompt.txt

import subprocess
import json
import time

# Function to run a shell command and return the output
def run_command(cmd):
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(f"Error running command: {cmd}")
        print(result.stderr.decode())
        return None
    return result.stdout.decode()

# Function to get the current CPU usage of all nodes
def get_node_cpu_usage():
    cpu_usage = {}
    output = run_command("kubectl top nodes --no-headers -o json")
    if output:
        nodes_data = json.loads(output)
        for node in nodes_data['items']:
            node_name = node['metadata']['name']
            cpu_percent = float(node['usage']['cpu'].strip('%'))
            cpu_usage[node_name] = cpu_percent
    return cpu_usage

# Function to find kubevirt pods running on a node
def get_kubevirt_pods_on_node(node):
    output = run_command(f"kubectl get pods --all-namespaces --field-selector=spec.nodeName={node} -o json")
    if output:
        pods_data = json.loads(output)
        kubevirt_pods = [pod for pod in pods_data['items'] if 'kubevirt' in pod['metadata']['name']]
        return kubevirt_pods
    return []

# Function to wait until no active live-migrations are running
def wait_for_no_active_migrations():
    print("Waiting for all active live-migrations to complete...")
    while True:
        output = run_command("kubectl get vmis --all-namespaces -o json")
        if output:
            vmis_data = json.loads(output)
            migrating_vms = [vmi for vmi in vmis_data['items'] if vmi['status'].get('migrationState', {}).get('completed') is False]
            if not migrating_vms:
                print("No active live-migrations found.")
                break
        time.sleep(10)

# Function to live-migrate a kubevirt VM pod
def live_migrate_vm(pod_name, pod_namespace):
    print(f"Initiating live migration of VM pod {pod_name} in namespace {pod_namespace}")
    migrate_cmd = f"kubectl virt migrate {pod_name} -n {pod_namespace}"
    run_command(migrate_cmd)

# Function to wait until a VM migration succeeds or fails
def wait_for_vm_migration(pod_name, pod_namespace):
    print(f"Waiting for VM pod {pod_name} to complete migration...")
    while True:
        output = run_command(f"kubectl get pod {pod_name} -n {pod_namespace} -o json")
        if output:
            pod_data = json.loads(output)
            phase = pod_data['status'].get('phase', '')
            if phase == 'Running':
                print(f"VM pod {pod_name} successfully migrated and is now running.")
                return True
            elif phase == 'Failed':
                print(f"VM pod {pod_name} migration failed.")
                return False
        time.sleep(5)

# Function to get the from-list (nodes with > 50% CPU that host kubevirt pods)
def get_from_list(cpu_usage, threshold=50):
    from_list = [node for node, usage in cpu_usage.items() if usage > threshold and get_kubevirt_pods_on_node(node)]
    return from_list

# Function to get the to-list (nodes with < 20% CPU)
def get_to_list(cpu_usage, threshold=20):
    to_list = {node: usage for node, usage in cpu_usage.items() if usage < threshold}
    return to_list

# Main function to handle the migration process
def perform_migration():
    # Wait for any active live-migrations to complete before starting
    wait_for_no_active_migrations()

    while True:
        # Step 1: Get CPU usage for all nodes
        cpu_usage = get_node_cpu_usage()
        if not cpu_usage:
            return

        # Step 2: Compute the from-list and to-list
        from_list = get_from_list(cpu_usage)
        to_list = get_to_list(cpu_usage)

        print(f"From-list (hot nodes): {from_list}")
        print(f"To-list (low nodes): {to_list}")

        # Step 3: If either list is empty, stop the process
        if not from_list or not to_list:
            print("Migration process complete. Either from-list or to-list is empty.")
            break

        # Step 4: Select the low-node with the lowest CPU usage from to-list
        low_node = min(to_list, key=to_list.get)
        print(f"Selected low-node: {low_node}")

        # Step 5: Select the hot-node with the highest CPU usage from from-list
        hot_node = max(from_list, key=lambda node: cpu_usage[node])
        print(f"Selected hot-node: {hot_node}")

        # Step 6: Get the list of VM pods (hot-vms) on the hot-node
        hot_vms = get_kubevirt_pods_on_node(hot_node)
        print(f"VM pods on hot-node {hot_node}: {hot_vms}")

        # Step 7: Iterate through each VM pod and try live migration
        while hot_vms:
            hot_vm = hot_vms.pop(0)  # Get a VM from the hot-vms list
            pod_name = hot_vm['metadata']['name']
            pod_namespace = hot_vm['metadata']['namespace']
            print(f"Attempting to live-migrate VM pod {pod_name} from node {hot_node}")

            # Try live-migration
            live_migrate_vm(pod_name, pod_namespace)

            # Wait for the migration to complete and check if successful
            if wait_for_vm_migration(pod_name, pod_namespace):
                print(f"VM pod {pod_name} successfully migrated.")
                break  # Stop if the migration is successful
            else:
                print(f"Retrying migration for next VM pod on {hot_node}...")

        # Step 8: Wait for all active live-migrations to complete
        wait_for_no_active_migrations()

        # Step 9: Recompute the from-list and to-list
        cpu_usage = get_node_cpu_usage()
        from_list = get_from_list(cpu_usage)
        to_list = get_to_list(cpu_usage)

# Run the migration process
if __name__ == "__main__":
    perform_migration()
