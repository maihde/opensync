import json
import boto3
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    SENDER = 'opensync@windsockmgmt.com'

    RECIPIENT = 'opensync@windsockmgmt.com'
    
    DESTINATION = {
        'ToAddresses': [
            RECIPIENT,
        ],
    }
    
    AWS_REGION = "us-east-1"
    
    for record in event.get("Records", []):
        body = record.get("body")
        if body is None:
            print("Record contained no body!")
            continue
        
        try:
            note = json.loads(body)
            flight_summary = note.get("body")
            
            if flight_summary is None:
                raise ValueError("Record contained no flight summary!")
            
            print(f"OpenSync Flight Log {flight_summary['beg_time']} : {flight_summary.get('origin', '')} > {flight_summary.get('destination', '')}")
            SUBJECT = f"OpenSync Flight Log {flight_summary['beg_time']} : {flight_summary.get('origin', '')} > {flight_summary.get('destination', '')}" 
            
            # The HTML body of the email.
        
            BODY_HTML = f"""
            <body>
                <h2>Flight Log</h2>
                <dl>
                    <dt>Origin</dt>
                    <dd>{flight_summary.get('origin', '')}</dd>
                    <dt>Destination</dt>
                    <dd>{flight_summary.get('destination', '')}</dd>
                    <dt>Hobbs Time</dt>
                    <dd>{flight_summary['hobbs_time']:.1f}</dd>
                    <dt>Flight Time</dt>
                    <dd>{flight_summary['flight_time']:.1f}</dd>
                    <dt>Fuel Consumed</dt>
                    <dd>{flight_summary['fuel_consumed']:.1f}</dd>
                    <dt>Fuel Remaining</dt>
                    <dd>{flight_summary['fuel_remaining']:.1f}</dd>
                </dl>
                
                <h2>Engine</h2>
                <dl>
                    <dt>Max CHT</dt>
                    <dd>{flight_summary['max_cht']}</dd>
                    <dt>Max EGT</dt>
                    <dd>{flight_summary['max_egt']}</dd>
                    <dt>Max TIT</dt>
                    <dd>{flight_summary['max_tit']}</dd>
                    <dt>Max Oil Temp</dt>
                    <dd>{flight_summary['max_oil_temp']:.0f}</dd>
                    <dt>Max Oil Pressure</dt>
                    <dd>{flight_summary['max_oil_pressure']:.1f}</dd>
                    <dt>Max Manifold Pressure</dt>
                    <dd>{flight_summary['max_manifold_pressure']:.1f}</dd>
                    <dt>Max RPM</dt>
                    <dd>{flight_summary['max_rpm']:.0f}</dd>
                </dl>
                
                <h2>Battery</h2>
                <dl>
                    <dt>Max Bat1 V</dt>
                    <dd>{flight_summary['min_bat1_volts']:.1f}</dd>
                    <dt>Max Bat2 V</dt>
                    <dd>{flight_summary['min_bat2_volts']:.1f}</dd>
                    <dt>Max Bat1 Amps</dt>
                    <dd>{flight_summary['max_bat1_amps']:.1f}</dd> 
                </dl>
                
                <h2>Performance</h2>
                <dl>
                    <dt>Max IAS</dt>
                    <dd>{flight_summary['max_ias']:.1f}</dd>
                    <dt>Max TAS</dt>
                    <dd>{flight_summary['max_tas']:.1f}</dd>
                    <dt>Max Lateral Accel</dt>
                    <dd>{flight_summary['max_lat_accel']:.1f}</dd> 
                    <dt>Max Norm Accel</dt>
                    <dd>{flight_summary['max_norm_accel']:.1f}</dd>
                </dl>
                
                <h2>Diagnostics</h2>
                <dl>
                    <dt>Tower Country</dt>
                    <dd>{note['tower_country']}</dd>
                    <dt>Tower Location</dt>
                    <dd>{note['tower_location']}</dd>
                </dl>
                <pre>
                {body}
                </pre>
            </body>
            """
        except Exception as e:
            print(e)
            SUBJECT = "OpenSync Flight Log Failure"
            
            BODY_HTML = f"""
            <body>
            Failed to process flight log.
            <pre>
            {e}
            </pre>
            <pre>
                {body}
            </pre>
            </body>
            """
        
        # The character encoding for the email.
        CHARSET = "UTF-8"
        
        # Create a new SES resource and specify a region.
        client = boto3.client('ses', region_name=AWS_REGION)
        
        # Try to send the email.
        response = ""
        try:
            #Provide the contents of the email.
            response = client.send_email(
                Destination = DESTINATION,
                Message={
                    'Body': {
                        'Html': {
                            'Charset': CHARSET,
                            'Data': BODY_HTML,
                        },
                    },
                    'Subject': {
                        'Charset': CHARSET,
                        'Data': SUBJECT,
                    },
                },
                Source=SENDER,
    
            )
        # Display an error if something goes wrong.	
        except ClientError as e:
            print(e.response['Error']['Message'])
        else:
            print("Email sent! Message ID:")
            print(response['MessageId'])
            print(RECIPIENT)
        
        return {
            'statusCode': 200,
            'body': json.dumps(response)
        }