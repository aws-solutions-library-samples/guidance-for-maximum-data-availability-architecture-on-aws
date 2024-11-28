/* This creates application schema */
-- connect as postgres 
create user cafeapp password 'Welcome1!';
grant all on database cafedb to cafeapp; 
-- connect as cafeapp
-- \c cafedb cafeapp
-- cafedb=> 
create schema cafe authorization cafeapp;
-- Orders in "raw" format
create table cafe.ordersraw(
 ordrid SERIAL PRIMARY KEY,
 ordrdgst char(20) UNIQUE NOT NULL, -- blake2b hash digest value
 ordrname varchar(40) NOT NULL, -- who ordered
 ordrppl integer NOT NULL, -- how many people to attend
 ordrdttm timestamp(0) NOT NULL, -- Date / Time no TZ no Seconds
 ordrtxt varchar(200) -- Optional notes
);

-- Dynamo DB Global table
-- docs.aws.amazon.com/amazondynamodb/latest/developerguide/V2globaltables.tutorial.html#V2creategt_cli 
aws dynamodb create-table \
    --table-name cafeordrsglbl \
    --attribute-definitions \
        AttributeName=ordrdgst,AttributeType=S \
    --key-schema \
        AttributeName=ordrdgst,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --stream-specification StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES \
    --region us-west-1
-- stackoverflow.com/questions/30866030/number-of-attributes-in-key-schema-must-match-the-number-of-attributes-defined-i
aws dynamodb update-table --table-name cafeordrsglbl --cli-input-json  \
'{
  "ReplicaUpdates":
  [
    {
      "Create": {
        "RegionName": "us-east-1"
      }
    }
  ]
}' \
--region=us-west-1
aws dynamodb describe-table --table-name cafeordrsglbl --region us-west-1 --output=table
